from datetime import date
from decimal import Decimal

from core.pricing import PromoWindow, effective_unit_price, prorate_unit_price

_SIZE_SYNONYMS = {"small": "S", "medium": "M", "large": "L", "s": "S", "m": "M", "l": "L"}


def _normalize_size(size):
    if size is None:
        return None
    return _SIZE_SYNONYMS.get(size.strip().lower(), size.strip().upper())


def _name_matches(query_name, product_name):
    q = query_name.strip().lower()
    p = product_name.strip().lower()
    return q in p or p in q


def find_sku(conn, product_name, color=None, size=None):
    """Resolve a natural-language product reference to a sku.

    Returns the sku string on an unambiguous match, or a list of candidate
    rows (dicts) when more than one variant matches — never guesses.
    """
    size_norm = _normalize_size(size)

    rows = conn.execute("SELECT * FROM products").fetchall()
    candidates = [r for r in rows if _name_matches(product_name, r["product_name"])]

    if color is not None:
        color_norm = color.strip().lower()
        candidates = [c for c in candidates if c["color"].strip().lower() == color_norm]

    if size_norm is not None:
        candidates = [c for c in candidates if c["size"].strip().upper() == size_norm]

    if len(candidates) == 1:
        return candidates[0]["sku"]
    return [
        {"sku": c["sku"], "product_name": c["product_name"], "color": c["color"], "size": c["size"]}
        for c in candidates
    ]


def find_customer(conn, name):
    """Resolve a customer name to a customer_id, or None (walk-in) if unknown."""
    row = conn.execute(
        "SELECT customer_id FROM customers WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    return row["customer_id"] if row else None


def get_unit_price(conn, sku, as_of_date):
    """Rule 5: list price adjusted for whichever promo gives the lowest price."""
    product = conn.execute(
        "SELECT product_id, category, retail_price FROM products WHERE sku = ?", (sku,)
    ).fetchone()

    promo_rows = conn.execute(
        """
        SELECT value, start_date, end_date FROM promotions
        WHERE (scope_type = 'product' AND scope_ref = ?)
           OR (scope_type = 'category' AND scope_ref = ?)
        """,
        (product["product_id"], product["category"]),
    ).fetchall()

    promotions = [
        PromoWindow(
            value_pct=Decimal(row["value"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
        )
        for row in promo_rows
    ]

    return effective_unit_price(
        list_price=Decimal(product["retail_price"]),
        promotions=promotions,
        sale_date=as_of_date,
    )


def _next_order_id(conn):
    rows = conn.execute("SELECT order_id FROM orders").fetchall()
    max_n = 1000
    for row in rows:
        try:
            max_n = max(max_n, int(row["order_id"].split("-")[1]))
        except (IndexError, ValueError):
            pass
    return f"O-{max_n + 1}"


def create_sale(
    conn, lines, payment_method, order_date, customer_name=None, order_discount_pct=Decimal("0")
):
    """Resolve and write a multi-line sale atomically.

    Every line is resolved and stock-checked before anything is written; a
    resolution failure or insufficient stock aborts the whole call with a
    structured error and no DB changes.
    """
    resolved_lines = []
    for line in lines:
        sku = find_sku(
            conn, line["product_name"], color=line.get("color"), size=line.get("size")
        )
        if not isinstance(sku, str):
            return {
                "error": "ambiguous_sku",
                "product_name": line["product_name"],
                "candidates": sku,
            }

        on_hand = conn.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()["on_hand_qty"]
        if line["quantity"] > on_hand:
            return {
                "error": "insufficient_stock",
                "sku": sku,
                "requested": line["quantity"],
                "available": on_hand,
            }

        unit_price = get_unit_price(conn, sku, order_date)
        resolved_lines.append({"sku": sku, "quantity": line["quantity"], "unit_price": unit_price})

    customer_id = find_customer(conn, customer_name) if customer_name else None
    order_id = _next_order_id(conn)

    conn.execute(
        "INSERT INTO orders (order_id, order_date, customer_id, order_discount_pct, payment_method)"
        " VALUES (?, ?, ?, ?, ?)",
        (order_id, order_date.isoformat(), customer_id, str(order_discount_pct), payment_method),
    )

    receipt_lines = []
    total = Decimal("0")
    for line_no, rl in enumerate(resolved_lines, start=1):
        conn.execute(
            "INSERT INTO order_lines (order_id, line_no, sku, quantity, unit_price)"
            " VALUES (?, ?, ?, ?, ?)",
            (order_id, line_no, rl["sku"], rl["quantity"], str(rl["unit_price"])),
        )
        conn.execute(
            "UPDATE inventory SET on_hand_qty = on_hand_qty - ? WHERE sku = ?",
            (rl["quantity"], rl["sku"]),
        )

        unit_price_paid = prorate_unit_price(rl["unit_price"], order_discount_pct)
        line_total = unit_price_paid * rl["quantity"]
        total += line_total
        receipt_lines.append(
            {
                "sku": rl["sku"],
                "quantity": rl["quantity"],
                "unit_price_paid": unit_price_paid,
                "line_total": line_total,
            }
        )

    conn.commit()
    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "lines": receipt_lines,
        "total": total,
    }
