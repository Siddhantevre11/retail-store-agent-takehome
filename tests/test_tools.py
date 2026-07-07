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


def test_find_sku_matches_common_synonym_jumper_for_hoodie(db_conn):
    sku = find_sku(db_conn, "jumper", color="Gray", size="Medium")

    assert sku == "HOOD-GRY-M"


def test_find_sku_matches_grey_british_spelling_for_gray(db_conn):
    sku = find_sku(db_conn, "hoodie", color="grey", size="Medium")

    assert sku == "HOOD-GRY-M"


def test_find_sku_matches_every_reviewed_hoodie_synonym(db_conn):
    # Audit lock for issue: confirms _SYNONYMS in tools/text.py is the
    # actual resolution mechanism (a small controlled dict), not the model
    # guessing ad hoc — every reviewed synonym must resolve deterministically.
    for synonym in ["sweater", "sweatshirt", "pullover"]:
        sku = find_sku(db_conn, synonym, color="Gray", size="Medium")
        assert sku == "HOOD-GRY-M", synonym


def test_find_sku_matches_every_reviewed_tee_synonym(db_conn):
    for synonym in ["t-shirt", "tshirt", "shirt"]:
        sku = find_sku(db_conn, synonym, color="Blue", size="Medium")
        assert sku == "TEE-BLU-M", synonym


def test_find_sku_matches_bag_synonym_for_tote(db_conn):
    sku = find_sku(db_conn, "bag")

    assert sku == "TOTE"


def test_find_sku_does_not_confidently_resolve_an_unknown_clothing_term(db_conn):
    # "cardigan" is neither a substring of any catalog product_name nor a
    # reviewed synonym — must fall through to no-match, never a guess.
    result = find_sku(db_conn, "cardigan")

    assert result == []


def test_find_sku_matches_when_color_word_is_folded_into_the_name(db_conn):
    # "Black Tee" isn't a substring of "Classic Tee" (or vice versa) even
    # though color="Black" is passed separately — found via the smoke
    # harness, where the model sometimes folds the color adjective into the
    # product_name phrase instead of (or in addition to) the color arg.
    sku = find_sku(db_conn, "Black Tee", color="Black", size="Medium")

    assert sku == "TEE-BLK-M"


def test_find_sku_still_matches_when_color_is_not_folded_into_the_name(db_conn):
    # Regression check: the already-working case (color passed separately,
    # not duplicated in product_name) must keep working.
    sku = find_sku(db_conn, "Tee", color="Black", size="Medium")

    assert sku == "TEE-BLK-M"


def test_find_sku_matches_when_size_word_is_folded_into_the_name(db_conn):
    # Same root cause as the color case above: "Small Tee" isn't a substring
    # of "Classic Tee" even though size="Small" is passed separately.
    sku = find_sku(db_conn, "Small Tee", color="Black", size="Small")

    assert sku == "TEE-BLK-S"


def test_find_sku_matches_color_word_folded_into_name_even_without_a_separate_color_arg(db_conn):
    # The model is inconsistent about whether it extracts the color into its
    # own argument or leaves it folded into product_name with color=None
    # entirely (observed via the smoke harness) — "Black" is still a known
    # color in the catalog regardless of which argument slot it arrived in.
    sku = find_sku(db_conn, "Black Tee", color=None, size="Medium")

    assert sku == "TEE-BLK-M"


def test_find_sku_ignores_an_invalid_color_and_resolves_by_name_alone(db_conn):
    # Complementary direction to the folding fix: "socks" isn't a real
    # catalog color, so it must be dropped rather than used as a filter —
    # letting the otherwise-unambiguous product name resolve correctly,
    # not falsely reporting no match.
    sku = find_sku(db_conn, "Wool Socks", color="socks", size=None)

    assert sku == "SOCK"


def test_find_sku_ignores_invalid_color_and_size_and_surfaces_real_ambiguity(db_conn):
    # Both slots are garbage ("banana" isn't a color, "XXL" isn't a size in
    # this catalog) — both must be dropped, and the genuine ambiguity of
    # "Tee" alone (6 variants) must surface as candidates, never a guess.
    result = find_sku(db_conn, "Tee", color="banana", size="XXL")

    assert isinstance(result, list)
    assert len(result) == 6


def test_find_sku_valid_color_and_size_are_unaffected_by_domain_validation(db_conn):
    # Regression: real values must resolve exactly as before.
    sku = find_sku(db_conn, "Tee", color="Blue", size="M")

    assert sku == "TEE-BLU-M"


def test_find_sku_returns_candidates_on_genuine_ambiguity(db_conn):
    result = find_sku(db_conn, "hoodie", size="Medium")

    assert isinstance(result, list)
    assert {c["sku"] for c in result} == {"HOOD-GRY-M", "HOOD-NVY-M"}


def test_find_customer_resolves_known_name(db_conn):
    assert find_customer(db_conn, "Sarah Chen") == "C-001"


def test_find_customer_returns_none_for_unknown_name(db_conn):
    assert find_customer(db_conn, "Nobody Nowhere") is None


def test_find_customer_matches_a_first_name_alone(db_conn):
    # "Sarah" is unambiguous — only one customer has that first name.
    assert find_customer(db_conn, "Sarah") == "C-001"


def test_find_customer_also_resolves_a_customer_id_directly(db_conn):
    # Found via the adversarial harness: the model occasionally passes back
    # a customer_id it just saw in a find_customer result, instead of the
    # name. Not ambiguous — a customer_id maps to exactly one customer — so
    # the tool can just handle it rather than silently falling back to walk-in.
    assert find_customer(db_conn, "C-001") == "C-001"


def test_get_unit_price_applies_seeded_promo_within_its_window(db_conn):
    price = get_unit_price(db_conn, "TEE-BLU-M", date(2026, 5, 3))

    assert price == Decimal("20.00")


def test_get_unit_price_uses_list_price_outside_promo_window(db_conn):
    price = get_unit_price(db_conn, "TEE-BLU-M", date(2026, 6, 19))

    assert price == Decimal("25.00")


def test_get_unit_price_returns_structured_error_for_unknown_sku(db_conn):
    # Found via the adversarial harness: the model can call this tool
    # standalone with a hallucinated/placeholder sku — must not crash.
    result = get_unit_price(db_conn, "__resolve_after_sku__", date(2026, 6, 19))

    assert result == {"error": "unknown_sku", "sku": "__resolve_after_sku__"}


def test_create_sale_is_unaffected_by_a_prior_placeholder_get_unit_price_call(db_conn):
    # Root-cause lock for the placeholder-sku pattern observed via the smoke
    # harness: create_sale resolves price internally from its own
    # already-resolved line skus (tools/sales.py create_sale -> get_unit_price
    # using the real sku) and never depends on any externally-supplied price
    # or on get_unit_price having been called first. A speculative/garbage
    # standalone call is a dead end, not a dependency, for the sale itself.
    placeholder_result = get_unit_price(db_conn, "__placeholder__", date(2026, 6, 19))
    assert placeholder_result == {"error": "unknown_sku", "sku": "__placeholder__"}

    result = create_sale(
        db_conn,
        lines=[{"product_name": "Canvas Tote", "color": None, "size": None, "quantity": 1}],
        payment_method="cash",
        order_discount_pct=Decimal("0"),
        order_date=date(2026, 6, 19),
    )

    assert result["total"] == Decimal("18.00")
    assert result["lines"][0]["unit_price_paid"] == Decimal("18.00")


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
