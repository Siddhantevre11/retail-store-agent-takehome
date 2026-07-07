from collections import defaultdict
from decimal import Decimal

from core.restocking import SupplierOption, select_supplier
from tools.ids import next_sequential_id
from tools.restocking import get_stockout_report
from tools.sales import find_sku
from tools.text import name_matches


def _find_supplier(conn, name):
    rows = conn.execute("SELECT supplier_id, supplier_name FROM suppliers").fetchall()
    matches = [r for r in rows if name_matches(name, r["supplier_name"])]
    return matches[0]["supplier_id"] if len(matches) == 1 else None


def _already_on_order(conn, sku):
    row = conn.execute(
        """
        SELECT 1 FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.po_id = pol.po_id
        WHERE pol.sku = ? AND po.status IN ('open', 'partial')
        """,
        (sku,),
    ).fetchone()
    return row is not None


def _select_supplier_for_product(conn, product_id):
    rows = conn.execute(
        "SELECT supplier_id, unit_cost, lead_time_days FROM supplier_catalog WHERE product_id = ?",
        (product_id,),
    ).fetchall()
    options = [
        SupplierOption(
            supplier_id=r["supplier_id"],
            unit_cost=Decimal(r["unit_cost"]),
            lead_time_days=r["lead_time_days"],
        )
        for r in rows
    ]
    return select_supplier(options)


def create_reorder_purchase_orders(conn, order_date):
    """Rule 4 + rule 7: for every flagged sku, open a PO line with the
    cheapest eligible supplier, sized to that sku's own reorder_qty. Every
    sku of a flagged product already appears in get_stockout_report (see
    docs/CONTEXT.md), so no separate "flagged only by velocity" branch is needed
    here — grouping by supplier and writing one PO per supplier is enough.
    """
    flagged = get_stockout_report(conn)

    lines_by_supplier = defaultdict(list)
    for row in flagged:
        if _already_on_order(conn, row["sku"]):
            continue
        supplier = _select_supplier_for_product(conn, row["product_id"])
        reorder_qty = conn.execute(
            "SELECT reorder_qty FROM inventory WHERE sku = ?", (row["sku"],)
        ).fetchone()["reorder_qty"]
        lines_by_supplier[supplier.supplier_id].append(
            {"sku": row["sku"], "quantity_ordered": reorder_qty}
        )

    created_pos = []
    for supplier_id, lines in lines_by_supplier.items():
        po_id = next_sequential_id(conn, "purchase_orders", "po_id", "PO", start=0)
        conn.execute(
            "INSERT INTO purchase_orders (po_id, supplier_id, order_date, status)"
            " VALUES (?, ?, ?, 'open')",
            (po_id, supplier_id, order_date.isoformat()),
        )
        for line_no, line in enumerate(lines, start=1):
            conn.execute(
                "INSERT INTO purchase_order_lines"
                " (po_id, line_no, sku, quantity_ordered, quantity_received)"
                " VALUES (?, ?, ?, ?, 0)",
                (po_id, line_no, line["sku"], line["quantity_ordered"]),
            )
        supplier_name = conn.execute(
            "SELECT supplier_name FROM suppliers WHERE supplier_id = ?", (supplier_id,)
        ).fetchone()["supplier_name"]
        created_pos.append(
            {
                "po_id": po_id,
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "lines": lines,
            }
        )

    conn.commit()
    return created_pos


def receive_purchase_order(
    conn,
    supplier_name,
    product_name,
    quantity_received,
    received_date,
    color=None,
    size=None,
    quantity_ordered=None,
):
    """Match an open/partial PO line for this supplier+sku and receive
    against it, auto-creating one if none exists. quantity_ordered only
    matters for auto-create sizing; it's ignored when a PO already exists.
    """
    supplier_id = _find_supplier(conn, supplier_name)
    sku = find_sku(conn, product_name, color=color, size=size)
    if not isinstance(sku, str):
        return {"error": "ambiguous_sku", "product_name": product_name, "candidates": sku}

    line = conn.execute(
        """
        SELECT pol.po_id, pol.line_no, pol.quantity_ordered, pol.quantity_received
        FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.po_id = pol.po_id
        WHERE po.supplier_id = ? AND pol.sku = ? AND po.status IN ('open', 'partial')
        ORDER BY po.order_date ASC
        LIMIT 1
        """,
        (supplier_id, sku),
    ).fetchone()

    if line is None:
        po_id = next_sequential_id(conn, "purchase_orders", "po_id", "PO", start=0)
        conn.execute(
            "INSERT INTO purchase_orders (po_id, supplier_id, order_date, status)"
            " VALUES (?, ?, ?, 'open')",
            (po_id, supplier_id, received_date.isoformat()),
        )
        ordered = quantity_ordered if quantity_ordered is not None else quantity_received
        new_received = quantity_received
        conn.execute(
            "INSERT INTO purchase_order_lines"
            " (po_id, line_no, sku, quantity_ordered, quantity_received) VALUES (?, 1, ?, ?, ?)",
            (po_id, sku, ordered, new_received),
        )
    else:
        po_id, line_no = line["po_id"], line["line_no"]
        ordered = line["quantity_ordered"]
        new_received = line["quantity_received"] + quantity_received
        conn.execute(
            "UPDATE purchase_order_lines SET quantity_received = ? WHERE po_id = ? AND line_no = ?",
            (new_received, po_id, line_no),
        )

    status = "received" if new_received >= ordered else "partial"
    conn.execute("UPDATE purchase_orders SET status = ? WHERE po_id = ?", (status, po_id))
    conn.execute(
        "UPDATE inventory SET on_hand_qty = on_hand_qty + ? WHERE sku = ?",
        (quantity_received, sku),
    )

    conn.commit()
    return {
        "po_id": po_id,
        "sku": sku,
        "quantity_received": quantity_received,
        "quantity_ordered": ordered,
        "status": status,
    }
