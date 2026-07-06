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


def test_create_promotion_category_matching_is_case_insensitive(db_conn):
    result = create_promotion(
        db_conn,
        description="test",
        value_pct=Decimal("10"),
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 25),
        category="Goods",
    )

    assert result["scope_ref"] == "goods"


def test_create_promotion_rejects_when_neither_product_nor_category_given(db_conn):
    # Found via the adversarial harness: even with a sharpened prompt telling
    # it to ask first, the model occasionally calls this with both null —
    # must not crash, must return a structured error.
    result = create_promotion(
        db_conn,
        description="10% off promotion",
        value_pct=Decimal("10"),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
    )

    assert result == {"error": "no_scope_given"}


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
