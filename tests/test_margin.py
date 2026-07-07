from datetime import date
from decimal import Decimal

from tools.margin import get_margin_report
from tools.returns import process_return


def test_get_margin_report_mug_no_discounts_no_returns(db_conn):
    report = get_margin_report(db_conn, period="last_month")

    mug = next(r for r in report if r["product_id"] == "P-MUG")
    assert mug["margin"] == Decimal("70.00")


def test_get_margin_report_tee_reflects_historical_promo_pricing(db_conn):
    report = get_margin_report(db_conn, period="last_month")

    tee = next(r for r in report if r["product_id"] == "P-TEE")
    assert tee["margin"] == Decimal("420.00")


def test_get_margin_report_hood_excludes_seeded_good_return(db_conn):
    # R-2001 (seed): 1 of O-1006's 2 HOOD-NVY-L units already returned, good,
    # return_date in May — that unit must be excluded from both revenue and cost.
    report = get_margin_report(db_conn, period="last_month")

    hood = next(r for r in report if r["product_id"] == "P-HOOD")
    assert hood["margin"] == Decimal("282.00")


def test_get_margin_report_is_unaffected_by_a_later_period_return(db_conn):
    # Process a NEW return today (June) against O-1006's last remaining
    # eligible Navy-L hoodie unit. Its return_date is outside May, so May's
    # already-closed margin must not change.
    process_return(
        db_conn,
        order_id="O-1006",
        product_name="hoodie",
        quantity=1,
        condition="good",
        return_date=date(2026, 6, 19),
        color="Navy",
        size="Large",
    )

    report = get_margin_report(db_conn, period="last_month")

    hood = next(r for r in report if r["product_id"] == "P-HOOD")
    assert hood["margin"] == Decimal("282.00")  # unchanged


def test_get_margin_report_rejects_this_month_as_incomplete(db_conn):
    # Root cause of the "does that affect this month's margin" mismatch: the
    # tool previously had no way to represent "this month" at all (the schema
    # enum only allowed "last_month"), forcing the model to silently send
    # last_month regardless of what was actually asked and rationalize the
    # substitution in prose. The current month is still in progress and its
    # margin figure would be misleading, so this must reject cleanly rather
    # than crash or silently substitute a different period.
    result = get_margin_report(db_conn, period="this_month")

    assert result == {
        "error": "unsupported_period",
        "period": "this_month",
        "reason": "the current month is still in progress; margin is only reported for complete months",
    }


def test_get_margin_report_damaged_return_does_not_reduce_margin(db_conn):
    # Damaged return dated WITHIN May, isolating this from the
    # period-boundedness rule — margin must still be unaffected, since only
    # good/restocked returns are excluded from margin.
    process_return(
        db_conn,
        order_id="O-1006",
        product_name="Canvas Tote",
        quantity=1,
        condition="damaged",
        return_date=date(2026, 5, 20),
    )

    report = get_margin_report(db_conn, period="last_month")

    tote = next(r for r in report if r["product_id"] == "P-TOTE")
    assert tote["margin"] == Decimal("108.20")  # unchanged
