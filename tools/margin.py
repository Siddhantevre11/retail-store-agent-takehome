from decimal import Decimal

from core.margin import MarginLine, compute_product_margins
from core.pricing import prorate_unit_price

_PERIODS = {"last_month": ("2026-05-01", "2026-05-31")}


def _good_returned_qty_in_period(conn, order_id, sku, start, end):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS n FROM returns
        WHERE order_id = ? AND sku = ? AND condition = 'good'
          AND return_date BETWEEN ? AND ?
        """,
        (order_id, sku, start, end),
    ).fetchone()
    return row["n"]


def get_margin_report(conn, period="last_month", top_n=5):
    """Rule 6: revenue minus Northwind cost, per product, over a period.

    Period-bounded: a return only affects the period its own return_date
    falls in — see _good_returned_qty_in_period's date filter. Only good
    (restocked) returns are excluded; damaged returns leave both revenue
    and cost counted (net_quantity is untouched by them).

    "this_month" is a recognized but unsupported period: the current month
    is still in progress, so its margin would be a moving, misleading
    number rather than the closed-period figure this report is for. Rejects
    explicitly rather than crashing or silently substituting last_month.
    """
    if period == "this_month":
        return {
            "error": "unsupported_period",
            "period": "this_month",
            "reason": "the current month is still in progress; margin is only reported for complete months",
        }
    start, end = _PERIODS[period]

    rows = conn.execute(
        """
        SELECT ol.order_id, ol.sku, ol.quantity, ol.unit_price, o.order_discount_pct,
               p.product_id, p.product_name
        FROM order_lines ol
        JOIN orders o ON o.order_id = ol.order_id
        JOIN products p ON p.sku = ol.sku
        WHERE o.order_date BETWEEN ? AND ?
        """,
        (start, end),
    ).fetchall()

    lines = []
    product_names = {}
    for row in rows:
        product_names[row["product_id"]] = row["product_name"]
        returned = _good_returned_qty_in_period(conn, row["order_id"], row["sku"], start, end)
        net_quantity = row["quantity"] - returned

        unit_cost = Decimal(
            conn.execute(
                "SELECT unit_cost FROM supplier_catalog WHERE supplier_id = 'SUP-NW' AND product_id = ?",
                (row["product_id"],),
            ).fetchone()["unit_cost"]
        )
        unit_price_paid = prorate_unit_price(
            Decimal(row["unit_price"]), Decimal(row["order_discount_pct"])
        )

        lines.append(
            MarginLine(
                product_id=row["product_id"],
                net_quantity=net_quantity,
                unit_price_paid=unit_price_paid,
                unit_cost=unit_cost,
            )
        )

    margins = compute_product_margins(lines)
    ranked = sorted(margins.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        {"product_id": pid, "product_name": product_names[pid], "margin": margin}
        for pid, margin in ranked
    ]
