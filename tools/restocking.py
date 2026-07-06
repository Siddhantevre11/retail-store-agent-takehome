from core.restocking import days_of_cover

MAY_START = "2026-05-01"
MAY_END = "2026-05-31"


def _monthly_units(conn, sku):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(ol.quantity), 0) AS n
        FROM order_lines ol
        JOIN orders o ON o.order_id = ol.order_id
        WHERE ol.sku = ? AND o.order_date BETWEEN ? AND ?
        """,
        (sku, MAY_START, MAY_END),
    ).fetchone()
    return row["n"]


def get_stockout_report(conn):
    """Rule 7: one row per SKU belonging to a flagged product — flagged if
    the SKU itself is at/below its own reorder_point, or its parent product's
    aggregate days-of-cover is under 14. Reports at SKU granularity with the
    product-level context attached, so restocking can act on it directly.
    """
    skus = conn.execute(
        "SELECT p.sku, p.product_id, i.on_hand_qty, i.reorder_point"
        " FROM products p JOIN inventory i ON i.sku = p.sku"
    ).fetchall()

    per_sku = []
    for row in skus:
        monthly_units = _monthly_units(conn, row["sku"])
        per_sku.append(
            {
                "sku": row["sku"],
                "product_id": row["product_id"],
                "on_hand_qty": row["on_hand_qty"],
                "reorder_point": row["reorder_point"],
                "below_reorder_point": row["on_hand_qty"] <= row["reorder_point"],
                "monthly_units": monthly_units,
            }
        )

    products = {}
    for r in per_sku:
        p = products.setdefault(r["product_id"], {"on_hand_qty": 0, "monthly_units": 0})
        p["on_hand_qty"] += r["on_hand_qty"]
        p["monthly_units"] += r["monthly_units"]

    product_cover = {
        pid: days_of_cover(p["on_hand_qty"], p["monthly_units"]) for pid, p in products.items()
    }

    report = []
    for r in per_sku:
        cover = product_cover[r["product_id"]]
        flagged_by_velocity = cover is not None and cover < 14
        if r["below_reorder_point"] or flagged_by_velocity:
            report.append(
                {
                    "sku": r["sku"],
                    "product_id": r["product_id"],
                    "on_hand_qty": r["on_hand_qty"],
                    "reorder_point": r["reorder_point"],
                    "below_reorder_point": r["below_reorder_point"],
                    "product_days_of_cover": cover,
                    "flagged_by_velocity": flagged_by_velocity,
                }
            )
    return report
