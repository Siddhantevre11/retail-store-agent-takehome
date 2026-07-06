from datetime import date

from tools.purchase_orders import create_reorder_purchase_orders, receive_purchase_order


def test_create_reorder_purchase_orders_opens_po_for_tote_from_northwind(db_conn):
    create_reorder_purchase_orders(db_conn, order_date=date(2026, 6, 19))

    line = db_conn.execute(
        """
        SELECT pol.sku, pol.quantity_ordered, pol.quantity_received, po.supplier_id, po.status
        FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.po_id = pol.po_id
        WHERE pol.sku = 'TOTE'
        """
    ).fetchone()

    assert line["supplier_id"] == "SUP-NW"
    assert line["quantity_ordered"] == 50
    assert line["quantity_received"] == 0
    assert line["status"] == "open"


def test_create_reorder_purchase_orders_does_not_duplicate_an_already_open_po(db_conn):
    # Found via the adversarial harness: calling this twice in a row (before
    # anything is received) used to open a second, redundant PO for the same
    # still-flagged sku instead of recognizing it's already on order.
    create_reorder_purchase_orders(db_conn, order_date=date(2026, 6, 19))
    second_result = create_reorder_purchase_orders(db_conn, order_date=date(2026, 6, 19))

    assert second_result == []
    po_count = db_conn.execute("SELECT COUNT(*) AS n FROM purchase_orders").fetchone()["n"]
    assert po_count == 1


def test_create_reorder_purchase_orders_result_includes_supplier_name(db_conn):
    result = create_reorder_purchase_orders(db_conn, order_date=date(2026, 6, 19))

    assert result[0]["supplier_name"] == "Northwind Supply"


def test_receive_purchase_order_partially_fulfills_existing_po(db_conn):
    create_reorder_purchase_orders(db_conn, order_date=date(2026, 6, 19))

    receive_purchase_order(
        db_conn,
        supplier_name="Northwind",
        product_name="Canvas Totes",
        quantity_received=40,
        received_date=date(2026, 6, 19),
    )

    line = db_conn.execute(
        """
        SELECT pol.quantity_received, po.status
        FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.po_id = pol.po_id
        WHERE pol.sku = 'TOTE'
        """
    ).fetchone()
    on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'"
    ).fetchone()["on_hand_qty"]

    assert line["quantity_received"] == 40
    assert line["status"] == "partial"
    assert on_hand == 44  # seed 4 + 40 received


def test_receive_purchase_order_auto_creates_sized_to_quantity_ordered_when_none_exists(db_conn):
    # No prior create_reorder_purchase_orders call — tests prompt 5 run in isolation.
    result = receive_purchase_order(
        db_conn,
        supplier_name="Northwind",
        product_name="Canvas Totes",
        quantity_received=40,
        received_date=date(2026, 6, 19),
        quantity_ordered=50,
    )

    assert result["status"] == "partial"

    line = db_conn.execute(
        "SELECT quantity_ordered, quantity_received FROM purchase_order_lines WHERE sku = 'TOTE'"
    ).fetchone()
    assert line["quantity_ordered"] == 50
    assert line["quantity_received"] == 40


def test_receive_purchase_order_auto_creates_fully_received_when_quantity_ordered_omitted(db_conn):
    result = receive_purchase_order(
        db_conn,
        supplier_name="Northwind",
        product_name="Canvas Totes",
        quantity_received=40,
        received_date=date(2026, 6, 19),
    )

    assert result["status"] == "received"

    line = db_conn.execute(
        "SELECT quantity_ordered, quantity_received FROM purchase_order_lines WHERE sku = 'TOTE'"
    ).fetchone()
    assert line["quantity_ordered"] == 40
    assert line["quantity_received"] == 40


def test_receive_purchase_order_surfaces_candidates_instead_of_guessing(db_conn):
    result = receive_purchase_order(
        db_conn,
        supplier_name="Northwind",
        product_name="hoodies",
        quantity_received=20,
        received_date=date(2026, 6, 19),
    )

    assert result["error"] == "ambiguous_sku"
    assert len(result["candidates"]) > 1

    # No PO written, no inventory changed.
    po_count = db_conn.execute("SELECT COUNT(*) AS n FROM purchase_orders").fetchone()["n"]
    assert po_count == 0
