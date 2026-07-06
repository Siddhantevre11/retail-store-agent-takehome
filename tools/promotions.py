from tools.ids import next_sequential_id
from tools.text import name_matches


def _resolve_product_id(conn, product_name):
    rows = conn.execute("SELECT DISTINCT product_id, product_name FROM products").fetchall()
    candidates = [r for r in rows if name_matches(product_name, r["product_name"])]
    if len(candidates) == 1:
        return candidates[0]["product_id"]
    return [{"product_id": c["product_id"], "product_name": c["product_name"]} for c in candidates]


def _known_categories(conn):
    return {r["category"] for r in conn.execute("SELECT DISTINCT category FROM products").fetchall()}


def create_promotion(
    conn, description, value_pct, start_date, end_date, product_name=None, category=None
):
    """Resolve product_name/category to scope_type/scope_ref internally —
    the model never supplies those raw DB-column values itself."""
    if category is None and product_name is None:
        return {"error": "no_scope_given"}

    if category is not None:
        category_norm = category.strip().lower()
        if category_norm not in _known_categories(conn):
            return {"error": "unknown_category", "category": category}
        scope_type, scope_ref = "category", category_norm
    else:
        product_id = _resolve_product_id(conn, product_name)
        if not isinstance(product_id, str):
            return {
                "error": "ambiguous_product",
                "product_name": product_name,
                "candidates": product_id,
            }
        scope_type, scope_ref = "product", product_id

    promo_id = next_sequential_id(conn, "promotions", "promo_id", "PR", start=0)
    conn.execute(
        "INSERT INTO promotions (promo_id, description, type, value, scope_type, scope_ref, start_date, end_date)"
        " VALUES (?, ?, 'percent_off', ?, ?, ?, ?, ?)",
        (
            promo_id,
            description,
            str(value_pct),
            scope_type,
            scope_ref,
            start_date.isoformat(),
            end_date.isoformat(),
        ),
    )
    conn.commit()
    return {
        "promo_id": promo_id,
        "scope_type": scope_type,
        "scope_ref": scope_ref,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
