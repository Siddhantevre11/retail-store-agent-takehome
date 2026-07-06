from datetime import date
from decimal import Decimal

from tools.sales import create_sale, find_customer, find_sku, get_unit_price


def test_find_sku_resolves_unambiguous_variant(db_conn):
    sku = find_sku(db_conn, "Classic Tee", color="Blue", size="Medium")

    assert sku == "TEE-BLU-M"


def test_find_sku_matches_plural_product_name(db_conn):
    # "hoodies" isn't a substring of "Pullover Hoodie" (or vice versa) — the
    # naive substring check misses this; needs singular-form normalization.
    sku = find_sku(db_conn, "hoodies", color="Gray", size="Medium")

    assert sku == "HOOD-GRY-M"


def test_find_sku_returns_candidates_on_genuine_ambiguity(db_conn):
    result = find_sku(db_conn, "hoodie", size="Medium")

    assert isinstance(result, list)
    assert {c["sku"] for c in result} == {"HOOD-GRY-M", "HOOD-NVY-M"}


def test_find_customer_resolves_known_name(db_conn):
    assert find_customer(db_conn, "Sarah Chen") == "C-001"


def test_find_customer_returns_none_for_unknown_name(db_conn):
    assert find_customer(db_conn, "Nobody Nowhere") is None


def test_get_unit_price_applies_seeded_promo_within_its_window(db_conn):
    price = get_unit_price(db_conn, "TEE-BLU-M", date(2026, 5, 3))

    assert price == Decimal("20.00")


def test_get_unit_price_uses_list_price_outside_promo_window(db_conn):
    price = get_unit_price(db_conn, "TEE-BLU-M", date(2026, 6, 19))

    assert price == Decimal("25.00")


def test_create_sale_single_line_walk_in_happy_path(db_conn):
    result = create_sale(
        db_conn,
        lines=[{"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 1}],
        payment_method="cash",
        order_discount_pct=Decimal("0"),
        order_date=date(2026, 6, 19),
    )

    assert "order_id" in result
    assert result["customer_id"] is None
    assert result["total"] == Decimal("18.00")
    assert result["lines"][0]["unit_price_paid"] == Decimal("18.00")

    on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'"
    ).fetchone()["on_hand_qty"]
    assert on_hand == 3


def test_create_sale_multi_line_walk_in_prompt_1(db_conn):
    result = create_sale(
        db_conn,
        lines=[
            {"product_name": "Classic Tee", "color": "Blue", "size": "Medium", "quantity": 2},
            {"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 1},
        ],
        payment_method="cash",
        order_discount_pct=Decimal("0"),
        order_date=date(2026, 6, 19),
    )

    assert result["total"] == Decimal("68.00")

    tee_on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TEE-BLU-M'"
    ).fetchone()["on_hand_qty"]
    tote_on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'"
    ).fetchone()["on_hand_qty"]
    assert tee_on_hand == 20
    assert tote_on_hand == 3


def test_create_sale_rejects_line_exceeding_on_hand_qty(db_conn):
    result = create_sale(
        db_conn,
        lines=[{"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 10}],
        payment_method="cash",
        order_discount_pct=Decimal("0"),
        order_date=date(2026, 6, 19),
    )

    assert result == {
        "error": "insufficient_stock",
        "sku": "TOTE",
        "requested": 10,
        "available": 4,
    }

    order_count = db_conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    tote_on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'"
    ).fetchone()["on_hand_qty"]
    assert order_count == 15  # unchanged from seed data
    assert tote_on_hand == 4  # unchanged


def test_create_sale_is_atomic_across_lines(db_conn):
    # First line (tee) is perfectly fine on its own; second line (10 totes)
    # oversells. Neither line should be written.
    result = create_sale(
        db_conn,
        lines=[
            {"product_name": "Classic Tee", "color": "Blue", "size": "Medium", "quantity": 1},
            {"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 10},
        ],
        payment_method="cash",
        order_discount_pct=Decimal("0"),
        order_date=date(2026, 6, 19),
    )

    assert result["error"] == "insufficient_stock"

    order_count = db_conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    tee_on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TEE-BLU-M'"
    ).fetchone()["on_hand_qty"]
    assert order_count == 15  # unchanged
    assert tee_on_hand == 22  # unchanged — the "fine" line was NOT written either


def test_create_sale_returns_candidates_for_ambiguous_line_without_writing(db_conn):
    # Prompt 3: "Ring up a hoodie in medium for Sarah Chen." — no color given,
    # and there are two mediums (Gray, Navy). Must ask, not guess.
    result = create_sale(
        db_conn,
        customer_name="Sarah Chen",
        lines=[{"product_name": "hoodie", "color": None, "size": "medium", "quantity": 1}],
        payment_method="card",
        order_discount_pct=Decimal("0"),
        order_date=date(2026, 6, 19),
    )

    assert result["error"] == "ambiguous_sku"
    assert {c["sku"] for c in result["candidates"]} == {"HOOD-GRY-M", "HOOD-NVY-M"}

    order_count = db_conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    assert order_count == 15  # unchanged
