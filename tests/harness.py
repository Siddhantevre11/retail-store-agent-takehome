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


@case("unknown_customer_name_becomes_walkin")
def _(client):
    conn, session, tool_log, replies = run_conversation(
        client, ["Ring up one Ceramic Mug for John Smith, paying cash, dated today."]
    )
    args, result = last_call(tool_log, "create_sale")
    assert result["customer_id"] is None, result


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
    # (CONTEXT.md), beyond the seed's TOTE-only case.
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


def main():
    load_dotenv()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    passed = 0
    failed = []
    for name, fn in CASES:
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

    total = len(CASES)
    rate = passed / total if total else 0
    print(f"\n{passed}/{total} passed ({rate:.0%})")
    if failed:
        print("Failed:", ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
