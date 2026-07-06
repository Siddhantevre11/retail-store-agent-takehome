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
