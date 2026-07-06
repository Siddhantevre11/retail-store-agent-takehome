from datetime import date
from decimal import Decimal

from tools.promotions import create_promotion
from tools.sales import get_unit_price


def test_create_promotion_by_product_name_applies_to_all_its_variants(db_conn):
    create_promotion(
        db_conn,
        description="Hoodie flash sale",
        value_pct=Decimal("20"),
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 22),
        product_name="hoodies",
    )

    price = get_unit_price(db_conn, "HOOD-GRY-M", date(2026, 6, 21))

    assert price == Decimal("48.00")


def test_create_promotion_by_product_name_does_not_affect_other_products(db_conn):
    # "hoodies" must resolve to scope_type='product' (P-HOOD), never
    # scope_type='category' (apparel) — a tee is also apparel and must be
    # unaffected by a hoodie-only promotion.
    create_promotion(
        db_conn,
        description="Hoodie flash sale",
        value_pct=Decimal("20"),
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 22),
        product_name="hoodies",
    )

    tee_price = get_unit_price(db_conn, "TEE-BLU-M", date(2026, 6, 21))

    assert tee_price == Decimal("25.00")


def test_create_promotion_does_not_alter_past_order_lines(db_conn):
    before = db_conn.execute(
        "SELECT unit_price FROM order_lines WHERE order_id = 'O-1006' AND sku = 'HOOD-NVY-L'"
    ).fetchone()["unit_price"]

    create_promotion(
        db_conn,
        description="Hoodie flash sale",
        value_pct=Decimal("20"),
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 22),
        product_name="hoodies",
    )

    after = db_conn.execute(
        "SELECT unit_price FROM order_lines WHERE order_id = 'O-1006' AND sku = 'HOOD-NVY-L'"
    ).fetchone()["unit_price"]
    assert before == after == "60.00"
