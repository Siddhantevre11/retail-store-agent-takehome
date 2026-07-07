import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from tests.conftest import FlakyConnProxy
from tools.returns import process_return


def test_process_return_good_condition_refunds_paid_price_and_restocks(db_conn):
    # O-1006 sold 2x HOOD-NVY-L at $60.00 with a 10% order discount ($54.00 paid).
    # R-2001 already returned 1 (good). Only 1 remains eligible.
    result = process_return(
        db_conn,
        order_id="O-1006",
        product_name="hoodie",
        quantity=1,
        condition="good",
        return_date=date(2026, 6, 19),
        color="Navy",
        size="Large",
    )

    assert result["refund_amount"] == Decimal("54.00")

    on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'HOOD-NVY-L'"
    ).fetchone()["on_hand_qty"]
    assert on_hand == 7  # seed 6 + this return's 1


def test_process_return_damaged_condition_refunds_but_does_not_restock(db_conn):
    result = process_return(
        db_conn,
        order_id="O-1006",
        product_name="Canvas Tote",
        quantity=1,
        condition="damaged",
        return_date=date(2026, 6, 19),
    )

    assert result["refund_amount"] == Decimal("16.20")

    on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'"
    ).fetchone()["on_hand_qty"]
    assert on_hand == 4  # unchanged — damaged, not restocked


def test_process_return_rejects_when_sku_was_not_on_that_order(db_conn):
    # O-1006 has no Ceramic Mug line at all — must not crash.
    result = process_return(
        db_conn,
        order_id="O-1006",
        product_name="Ceramic Mug",
        quantity=1,
        condition="good",
        return_date=date(2026, 6, 19),
    )

    assert result == {"error": "sku_not_on_order", "order_id": "O-1006", "sku": "MUG"}


def test_process_return_rolls_back_completely_on_a_mid_write_failure(db_conn):
    # Same atomicity gap as create_sale: the return INSERT and the
    # inventory UPDATE (for a good-condition return) aren't wrapped in a
    # transaction. Fault-injected after the return row would have been
    # written but before the inventory update completes — both must roll
    # back together, not leave a dangling returns row with unchanged
    # inventory (a refund recorded but stock never actually restocked).
    flaky_conn = FlakyConnProxy(db_conn, fail_sql_prefix="UPDATE inventory", fail_on_nth=1)

    with pytest.raises(sqlite3.OperationalError):
        process_return(
            flaky_conn,
            order_id="O-1006",
            product_name="hoodie",
            quantity=1,
            condition="good",
            return_date=date(2026, 6, 19),
            color="Navy",
            size="Large",
        )

    return_count = db_conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'HOOD-NVY-L'"
    ).fetchone()["on_hand_qty"]

    assert return_count == 1  # only the seeded R-2001, no dangling new row
    assert on_hand == 6  # unchanged from seed


def test_process_return_rejects_over_return_without_writing(db_conn):
    # Only 1 of the 2 HOOD-NVY-L units on O-1006 is still eligible (R-2001
    # already returned 1, good condition). Requesting 2 more must be rejected.
    result = process_return(
        db_conn,
        order_id="O-1006",
        product_name="hoodie",
        quantity=2,
        condition="good",
        return_date=date(2026, 6, 19),
        color="Navy",
        size="Large",
    )

    assert result == {
        "error": "over_return",
        "sku": "HOOD-NVY-L",
        "requested": 2,
        "remaining_eligible": 1,
    }

    return_count = db_conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()["n"]
    on_hand = db_conn.execute(
        "SELECT on_hand_qty FROM inventory WHERE sku = 'HOOD-NVY-L'"
    ).fetchone()["on_hand_qty"]
    assert return_count == 1  # only the seeded R-2001, nothing new written
    assert on_hand == 6  # unchanged from seed
