"""Adversarial harness: runs prompts through the real agent loop (issue #9).

Each case gets a fresh in-memory DB (via agent.runner.run_conversation) and
asserts on the resulting DB state / tool-call log — never on the model's
prose. Run directly: `python -m tests.harness`.
"""

import os
import sys
from decimal import Decimal

from dotenv import load_dotenv
from openai import OpenAI

from agent.runner import run_conversation

CASES = []


def case(name):
    def decorator(fn):
        CASES.append((name, fn))
        return fn

    return decorator


def last_call(tool_log, name):
    for call_name, args, result in reversed(tool_log):
        if call_name == name:
            return args, result
    raise AssertionError(f"no call to {name!r} found in tool log")


@case("prompt_1_multiline_walkin_sale")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up two Classic Tees, Blue Medium, and one Canvas Tote for a "
            "walk-in paying cash, dated today."
        ],
    )
    args, result = last_call(tool_log, "create_sale")
    assert result["total"] == Decimal("68.00"), result
    assert result["customer_id"] is None, result


@case("overlapping_product_and_category_promos_lowest_price_wins")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put hoodies on 30% off from 2026-06-20 to 2026-06-25.",
            "Put all apparel on 10% off from 2026-06-20 to 2026-06-25.",
            "What's the price of a Gray Medium hoodie on 2026-06-22?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "42.00", result  # 30% off wins over 10%


@case("over_returning_a_line_is_rejected")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Sarah Chen wants to return two Navy Large hoodies from order "
            "O-1006, good condition."
        ],
    )
    returns_count = conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    assert returns_count == 1, "only the seeded R-2001 should exist — nothing new written"


@case("discount_and_historical_promo_combine")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up two Classic Tees, Blue Small, for a walk-in paying card, "
            "with a 10% order discount, dated 2026-05-03."
        ],
    )
    args, result = last_call(tool_log, "create_sale")
    assert result["total"] == Decimal("36.00"), result  # $25->promo $20->10% off=$18 * 2


@case("receive_against_nonexistent_po")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "A purchase order for 20 Wool Socks from Northwind is open and 15 "
            "arrived — receive them, dated today."
        ],
    )
    args, result = last_call(tool_log, "receive_purchase_order")
    assert result["status"] == "partial", result
    assert result["quantity_ordered"] == 20, result


@case("reorder_when_nothing_is_low")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "50 Canvas Totes arrived from Northwind today, no purchase order "
            "on file for them.",
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today.",
        ],
    )
    args, result = last_call(tool_log, "create_reorder_purchase_orders")
    assert result == [], result


@case("unknown_customer_name_is_rejected_not_silently_walked_in")
def _(client):
    # "John Smith" is a stated name, not an omission — must not silently
    # ring up as a walk-in (that's reserved for when no name is given at
    # all). Reversed from the prior behavior this case used to assert on,
    # per the project's own "ask, don't silently default" philosophy.
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up one Ceramic Mug for John Smith, paying cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result.get("error") == "unknown_customer", result
    order_count = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    assert order_count == 15, "no order should have been written for an unresolved customer"


@case("product_synonym_jumper_for_hoodie")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up a gray medium jumper for a walk-in, cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result.get("lines", [{}])[0].get("sku") == "HOOD-GRY-M", result


@case("multiturn_edit_after_completed_sale_asks_instead_of_duplicating")
def _(client):
    # Found via this harness: without an explicit instruction, the model used
    # to silently ring up a second full sale instead of recognizing it can't
    # edit a completed one. Fixed in the system prompt (agent/runner.py).
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up one Wool Socks for a walk-in, cash, dated today.",
            "Actually, make that three.",
        ],
    )
    create_sale_calls = [n for n, a, r in tool_log if n == "create_sale"]
    assert len(create_sale_calls) == 1, "should ask for clarification, not ring up a second sale"


@case("promo_start_date_is_inclusive")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put Wool Socks on 50% off from 2026-06-20 to 2026-06-22.",
            "What's the price of Wool Socks on 2026-06-20?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "4.50", result


@case("promo_end_date_is_inclusive")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put Wool Socks on 50% off from 2026-06-20 to 2026-06-22.",
            "What's the price of Wool Socks on 2026-06-22?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "4.50", result


@case("promo_day_after_window_does_not_apply")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put Wool Socks on 50% off from 2026-06-20 to 2026-06-22.",
            "What's the price of Wool Socks on 2026-06-23?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "9.00", result


@case("category_wide_promo_applies_to_every_product_in_it")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put all goods on 15% off from 2026-06-20 to 2026-06-25.",
            "What's the price of a Canvas Tote on 2026-06-21?",
            "What's the price of a Ceramic Mug on 2026-06-21?",
        ],
    )
    prices = [r["unit_price"] for n, a, r in tool_log if n == "get_unit_price"]
    assert prices == ["15.30", "10.20"], prices


@case("sequential_returns_exhaust_remaining_then_reject")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Sarah Chen is returning one Navy Large hoodie from order O-1006, "
            "good condition.",
            "Sarah Chen is returning one more Navy Large hoodie from order "
            "O-1006, good condition.",
        ],
    )
    returns_count = conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    assert returns_count == 2, "first return (R-2001 already existed) should succeed once more, then stop"


@case("partial_po_receipt_then_remainder_completes_it")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today.",
            "40 Canvas Totes arrived from Northwind today, receive them.",
            "The remaining 10 Canvas Totes arrived from Northwind today too, "
            "receive them.",
        ],
    )
    line = conn.execute(
        """
        SELECT pol.quantity_received, po.status FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.po_id = pol.po_id WHERE pol.sku = 'TOTE'
        """
    ).fetchone()
    assert line["quantity_received"] == 50, dict(line)
    assert line["status"] == "received", dict(line)


@case("selling_exactly_all_remaining_stock_succeeds")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up four Canvas Totes for a walk-in, cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert "order_id" in result, result
    on_hand = conn.execute("SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'").fetchone()[
        "on_hand_qty"
    ]
    assert on_hand == 0, on_hand


@case("completely_unknown_product_does_not_create_a_sale")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up one Flying Carpet for a walk-in, cash, dated today."]
    )
    order_count = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    assert order_count == 15, "no order should have been written for a nonexistent product"


@case("oversell_beyond_on_hand_stock_is_rejected")
def _(client):
    # TOTE has on_hand_qty 4 in seed data. Asking for 50 must be rejected by
    # create_sale's insufficient_stock guard, not silently clamped or sold
    # short — and no order/order_lines row should be written at all.
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up fifty Canvas Totes for a walk-in, cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result.get("error") == "insufficient_stock", result
    order_count = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    assert order_count == 15, "no order should have been written when stock was insufficient"
    on_hand = conn.execute("SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'").fetchone()[
        "on_hand_qty"
    ]
    assert on_hand == 4, "inventory must be untouched on a rejected oversell"


@case("pronoun_reference_to_named_customer_across_turns")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up one Ceramic Mug for Marcus Reed, paying card, dated today.",
            "Now sell him a Canvas Tote too, same terms.",
        ],
    )
    create_sale_calls = [(a, r) for n, a, r in tool_log if n == "create_sale"]
    assert len(create_sale_calls) == 2, create_sale_calls
    _, second_result = create_sale_calls[1]
    assert second_result["customer_id"] == "C-002", second_result


@case("margin_report_respects_top_n")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["What are my top 2 products by profit margin last month?"]
    )
    args, result = last_call(tool_log, "get_margin_report")
    assert len(result) == 2, result
    assert result[0]["product_id"] == "P-TEE", result


@case("reorder_flags_only_the_specific_sku_that_dropped_below_reorder_point")
def _(client):
    # HOOD-NVY-L: on_hand 6, reorder_point 5. Selling 3 more drops it to 3
    # (<=5), but the other 3 hoodie skus and the aggregate hoodie days-of-cover
    # stay healthy — only this one sku should get reordered, not the whole
    # hoodie product line. Real test of the sku-level PO granularity decision
    # (docs/CONTEXT.md), beyond the seed's TOTE-only case.
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up three Navy Large hoodies for a walk-in, cash, dated today.",
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today.",
        ],
    )
    args, result = last_call(tool_log, "create_reorder_purchase_orders")
    all_skus = {line["sku"] for po in result for line in po["lines"]}
    # TOTE is always flagged in the seed data too — the point of this case is
    # that no OTHER hoodie sku got swept in with HOOD-NVY-L.
    assert all_skus == {"HOOD-NVY-L", "TOTE"}, result


@case("ambiguous_product_reference_on_a_return_asks_instead_of_guessing")
def _(client):
    # O-1012 has three hoodie lines (Gray-M, Navy-M, Gray-L) — "a hoodie"
    # with no color/size can't resolve to one sku.
    conn, session, tool_log, replies = run_conversation(
        client, ["Return a hoodie from order O-1012, good condition, one unit."]
    )
    returns_count = conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    assert returns_count == 1, "only the seeded R-2001 should exist — ambiguous ref must not guess"


@case("promotion_with_no_scope_stated_does_not_silently_pick_one")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Create a 10% off promotion from 2026-07-01 to 2026-07-05."]
    )
    promo_count = conn.execute("SELECT COUNT(*) AS n FROM promotions").fetchone()["n"]
    assert promo_count == 1, "only the seeded PR-001 should exist — must ask which product/category"


@case("supplier_name_matching_is_case_insensitive")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["40 canvas totes arrived from northwind today, receive them."]
    )
    args, result = last_call(tool_log, "receive_purchase_order")
    assert result["status"] in {"partial", "received"}, result
    on_hand = conn.execute("SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'").fetchone()[
        "on_hand_qty"
    ]
    assert on_hand == 44, on_hand


@case("customer_name_matching_is_case_insensitive")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up one ceramic mug for sarah chen, paying cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result["customer_id"] == "C-001", result


@case("margin_report_defaults_to_top_five_when_unspecified")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["What were my top products by profit margin last month?"]
    )
    args, result = last_call(tool_log, "get_margin_report")
    assert len(result) == 5, result


@case("return_of_a_product_not_on_that_order_is_rejected")
def _(client):
    # O-1006 has no Ceramic Mug line at all.
    conn, session, tool_log, replies = run_conversation(
        client,
        ["Return a Ceramic Mug from order O-1006, good condition, dated today."],
    )
    returns_count = conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    assert returns_count == 1, "only the seeded R-2001 should exist"


@case("stockout_report_flags_only_tote_on_seed_data")
def _(client):
    conn, session, tool_log, replies = run_conversation(client, ["What's about to stock out?"])
    args, result = last_call(tool_log, "get_stockout_report")
    assert {row["sku"] for row in result} == {"TOTE"}, result


@case("receiving_a_specific_variant_only_touches_that_pos_line")
def _(client):
    # Flag two different hoodie skus, reorder both onto one Northwind PO,
    # then receive a fully-specified variant — must only touch that line.
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up three Navy Large hoodies for a walk-in, cash, dated today.",
            "Ring up three Gray Medium hoodies for a walk-in, cash, dated today.",
            "Reorder anything below its reorder point, from the best supplier, "
            "dated today.",
            "20 Gray Medium hoodies arrived from Northwind today, receive them.",
        ],
    )
    gray_line = conn.execute(
        """
        SELECT pol.quantity_received, po.status FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.po_id = pol.po_id WHERE pol.sku = 'HOOD-GRY-M'
        """
    ).fetchone()
    navy_line = conn.execute(
        """
        SELECT pol.quantity_received FROM purchase_order_lines pol WHERE pol.sku = 'HOOD-NVY-L'
        """
    ).fetchone()
    assert gray_line["quantity_received"] == 20, dict(gray_line)
    assert navy_line["quantity_received"] == 0, dict(navy_line)


@case("british_spelling_grey_matches_gray")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up one grey medium hoodie for a walk-in, cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result.get("lines", [{}])[0].get("sku") == "HOOD-GRY-M", result


@case("first_name_alone_resolves_unambiguous_customer")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up one Ceramic Mug for Sarah, paying cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result["customer_id"] == "C-001", result


@case("return_against_a_nonexistent_order_is_rejected_gracefully")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Return one Canvas Tote from order O-9999, good condition, dated today."]
    )
    returns_count = conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    assert returns_count == 1, "only the seeded R-2001 should exist"


@case("hundred_percent_off_promo_prices_at_zero")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put Wool Socks on 100% off from 2026-06-20 to 2026-06-22.",
            "What's the price of Wool Socks on 2026-06-21?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "0.00", result


@case("reordering_twice_in_a_row_does_not_duplicate_the_po")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today.",
            "Reorder anything that's below its reorder point again, from the "
            "best supplier. Date it today.",
        ],
    )
    po_count = conn.execute("SELECT COUNT(*) AS n FROM purchase_orders").fetchone()["n"]
    assert po_count == 1, "second reorder call must not duplicate an already-open PO"


@case("apparel_category_promo_does_not_affect_goods")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put all apparel on 20% off from 2026-06-20 to 2026-06-25.",
            "What's the price of a Ceramic Mug on 2026-06-21?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "12.00", result  # unaffected — mug is goods, not apparel


@case("receiving_completely_unknown_product_is_rejected_gracefully")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        ["50 Flying Carpets arrived from Northwind today, receive them."],
    )
    po_count = conn.execute("SELECT COUNT(*) AS n FROM purchase_orders").fetchone()["n"]
    assert po_count == 0, "no PO should be written for a nonexistent product"


@case("margin_report_top_n_larger_than_product_count_returns_all")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["What are my top 10 products by profit margin last month?"]
    )
    args, result = last_call(tool_log, "get_margin_report")
    assert len(result) == 5, result  # only 5 products exist at all


@case("multiline_sale_with_one_ambiguous_line_writes_nothing")
def _(client):
    # Tote line is fine on its own; hoodie line (no color/size) is ambiguous.
    # Whole sale must abort — atomicity holds even when only one line is bad.
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Ring up one Canvas Tote and one hoodie in medium for a walk-in, "
            "cash, dated today."
        ],
    )
    order_count = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    assert order_count == 15, "ambiguous line must abort the whole sale, not just skip itself"


@case("promotion_category_matching_is_case_insensitive")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Put all Goods on 15% off from 2026-06-20 to 2026-06-25.",
            "What's the price of a Canvas Tote on 2026-06-21?",
        ],
    )
    args, result = last_call(tool_log, "get_unit_price")
    assert result["unit_price"] == "15.30", result


@case("sample_prompts_6_7_9_sequenced_margin_reflects_only_may_dated_returns")
def _(client):
    # Mirrors the brief's own sample-prompt sequencing: two returns processed
    # today (June), then a "last month" margin query. Both returns are
    # June-dated, so neither should move May's already-closed HOOD/TOTE margin
    # beyond what the seeded (May-dated) R-2001 already accounts for.
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Sarah Chen is returning one Navy Large hoodie from order O-1006. "
            "It's in good condition.",
            "Return the Canvas Tote from order O-1006 — it came back damaged.",
            "What were my top five products by profit margin last month?",
        ],
    )
    args, result = last_call(tool_log, "get_margin_report")
    by_id = {r["product_id"]: r["margin"] for r in result}
    assert by_id["P-HOOD"] == Decimal("282.00"), result  # unchanged by the June return
    assert by_id["P-TOTE"] == Decimal("108.20"), result  # damaged never affects margin


@case("sample_prompt_5_literal_text")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client,
        [
            "Reorder anything that's below its reorder point, from the best "
            "supplier. Date it today.",
            "A purchase order for 50 Canvas Totes from Northwind is open and "
            "40 arrived — receive them, dated today.",
        ],
    )
    args, result = last_call(tool_log, "receive_purchase_order")
    assert result["status"] == "partial", result
    assert result["quantity_received"] == 40, result


def main():
    load_dotenv()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    filter_substr = sys.argv[1] if len(sys.argv) > 1 else None
    cases = (
        [(n, fn) for n, fn in CASES if filter_substr in n] if filter_substr else CASES
    )

    passed = 0
    failed = []
    for name, fn in cases:
        try:
            fn(client)
            passed += 1
            print(f"PASS  {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001 - report and keep going
            failed.append(name)
            print(f"ERROR {name}: {e!r}")

    total = len(cases)
    rate = passed / total if total else 0
    print(f"\n{passed}/{total} passed ({rate:.0%})")
    if failed:
        print("Failed:", ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
