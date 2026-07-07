from datetime import date
from decimal import Decimal

from core.pricing import PromoWindow, effective_unit_price, prorate_unit_price
from tools.ids import next_sequential_id
from tools.text import name_matches

_SIZE_SYNONYMS = {"small": "S", "medium": "M", "large": "L", "s": "S", "m": "M", "l": "L"}
_COLOR_SYNONYMS = {"grey": "gray"}


def _normalize_size(size):
    if size is None:
        return None
    return _SIZE_SYNONYMS.get(size.strip().lower(), size.strip().upper())


def _normalize_color(color):
    c = color.strip().lower()
    return _COLOR_SYNONYMS.get(c, c)


def _strip_word(text, word):
    kept = [w for w in text.split() if w.lower() != word.lower()]
    cleaned = " ".join(kept)
    return cleaned if cleaned else text


def _known_descriptor_words(conn, column, synonyms):
    """Color/size vocabulary the model might fold into product_name instead
    of (or in addition to) its own argument — the catalog's actual values
    plus any recognized synonyms (e.g. 'grey', 'small')."""
    values = {
        row[0].strip().lower()
        for row in conn.execute(f"SELECT DISTINCT {column} FROM products").fetchall()
        if row[0]
    }
    return values | set(synonyms.keys()) | {v.lower() for v in synonyms.values()}


def _validate_domain_value(conn, column, synonyms, value):
    """A color/size argument only carries filtering information if it's a
    real catalog value or a recognized synonym. A mis-slotted word that
    isn't ("socks" as a color, "XXL" as a size — anything the hidden
    prompts throw, not just the specific words seen so far) is dropped
    (treated as unspecified) rather than used to filter, so it can't
    silently exclude the correct candidate. This is the complementary
    direction to _extract_and_strip below: that recovers a real descriptor
    word folded into the wrong slot (product_name); this rejects a fake one
    that landed in the right-shaped slot.
    """
    if value is None:
        return None
    known = _known_descriptor_words(conn, column, synonyms)
    return value if value.strip().lower() in known else None


def _extract_and_strip(conn, column, synonyms, query_name, explicit_value):
    """If explicit_value is None, look for a known descriptor word (e.g. a
    color name) folded into query_name and recover it as the effective
    value — the customer did state it, just not in its own argument slot.
    Either way, strip that word out of query_name so a duplicated color/size
    word can't defeat the product-name substring match.
    """
    effective_value = explicit_value
    if effective_value is None:
        known = _known_descriptor_words(conn, column, synonyms)
        for word in query_name.split():
            if word.lower() in known:
                effective_value = word
                break
    if effective_value is not None:
        query_name = _strip_word(query_name, effective_value)
    return query_name, effective_value


def find_sku(conn, product_name, color=None, size=None):
    """Resolve a natural-language product reference to a sku.

    Returns the sku string on an unambiguous match, or a list of candidate
    rows (dicts) when more than one variant matches — never guesses.
    """
    color = _validate_domain_value(conn, "color", _COLOR_SYNONYMS, color)
    size = _validate_domain_value(conn, "size", _SIZE_SYNONYMS, size)

    query_name = product_name
    query_name, color = _extract_and_strip(conn, "color", _COLOR_SYNONYMS, query_name, color)
    query_name, size = _extract_and_strip(conn, "size", _SIZE_SYNONYMS, query_name, size)
    size_norm = _normalize_size(size)

    rows = conn.execute("SELECT * FROM products").fetchall()
    candidates = [r for r in rows if name_matches(query_name, r["product_name"])]

    if color is not None:
        color_norm = _normalize_color(color)
        candidates = [c for c in candidates if _normalize_color(c["color"]) == color_norm]

    if size_norm is not None:
        candidates = [c for c in candidates if c["size"].strip().upper() == size_norm]

    if len(candidates) == 1:
        return candidates[0]["sku"]
    return [
        {"sku": c["sku"], "product_name": c["product_name"], "color": c["color"], "size": c["size"]}
        for c in candidates
    ]


def find_customer(conn, name):
    """Resolve a customer reference. Accepts a full name, a partial name
    (e.g. just a first name, if unambiguous), or an already-resolved
    customer_id.

    Returns None only when no name was given at all — a walk-in, a defined
    business meaning, not missing information. Returns the customer_id
    string on an unambiguous match. Otherwise returns a list of candidate
    customer dicts (empty if the given name matched no one, more than one
    if genuinely ambiguous) — a name that WAS given but didn't resolve is
    never silently collapsed into the same None a walk-in would produce.
    """
    if not name:
        return None

    exact = conn.execute(
        "SELECT customer_id FROM customers WHERE LOWER(name) = LOWER(?) OR customer_id = ?",
        (name, name),
    ).fetchone()
    if exact:
        return exact["customer_id"]

    rows = conn.execute("SELECT customer_id, name FROM customers").fetchall()
    matches = [r for r in rows if name.strip().lower() in r["name"].lower()]
    if len(matches) == 1:
        return matches[0]["customer_id"]
    return [{"customer_id": r["customer_id"], "name": r["name"]} for r in matches]


def get_unit_price(conn, sku, as_of_date):
    """Rule 5: list price adjusted for whichever promo gives the lowest price."""
    product = conn.execute(
        "SELECT product_id, category, retail_price FROM products WHERE sku = ?", (sku,)
    ).fetchone()
    if product is None:
        return {"error": "unknown_sku", "sku": sku}

    promo_rows = conn.execute(
        """
        SELECT value, start_date, end_date FROM promotions
        WHERE (scope_type = 'product' AND scope_ref = ?)
           OR (scope_type = 'category' AND scope_ref = ?)
        """,
        (product["product_id"], product["category"]),
    ).fetchall()

    promotions = [
        PromoWindow(
            value_pct=Decimal(row["value"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
        )
        for row in promo_rows
    ]

    return effective_unit_price(
        list_price=Decimal(product["retail_price"]),
        promotions=promotions,
        sale_date=as_of_date,
    )


def _next_order_id(conn):
    return next_sequential_id(conn, "orders", "order_id", "O", start=1000)


def create_sale(
    conn, lines, payment_method, order_date, customer_name=None, order_discount_pct=Decimal("0")
):
    """Resolve and write a multi-line sale atomically.

    Every line is resolved and stock-checked before anything is written; a
    resolution failure or insufficient stock aborts the whole call with a
    structured error and no DB changes.
    """
    resolved_lines = []
    for line in lines:
        sku = find_sku(
            conn, line["product_name"], color=line.get("color"), size=line.get("size")
        )
        if not isinstance(sku, str):
            return {
                "error": "ambiguous_sku",
                "product_name": line["product_name"],
                "candidates": sku,
            }

        on_hand = conn.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()["on_hand_qty"]
        if line["quantity"] > on_hand:
            return {
                "error": "insufficient_stock",
                "sku": sku,
                "requested": line["quantity"],
                "available": on_hand,
            }

        unit_price = get_unit_price(conn, sku, order_date)
        resolved_lines.append({"sku": sku, "quantity": line["quantity"], "unit_price": unit_price})

    customer_id = find_customer(conn, customer_name)
    if customer_id is not None and not isinstance(customer_id, str):
        return {
            "error": "unknown_customer",
            "customer_name": customer_name,
            "candidates": customer_id,
        }

    order_id = _next_order_id(conn)

    receipt_lines = []
    total = Decimal("0")
    # Atomic by transaction, not just by front-loaded validation: `with conn`
    # commits on clean exit and rolls back the whole write phase (order +
    # every line's order_lines/inventory write so far) on any exception.
    with conn:
        conn.execute(
            "INSERT INTO orders (order_id, order_date, customer_id, order_discount_pct, payment_method)"
            " VALUES (?, ?, ?, ?, ?)",
            (order_id, order_date.isoformat(), customer_id, str(order_discount_pct), payment_method),
        )

        for line_no, rl in enumerate(resolved_lines, start=1):
            conn.execute(
                "INSERT INTO order_lines (order_id, line_no, sku, quantity, unit_price)"
                " VALUES (?, ?, ?, ?, ?)",
                (order_id, line_no, rl["sku"], rl["quantity"], str(rl["unit_price"])),
            )
            conn.execute(
                "UPDATE inventory SET on_hand_qty = on_hand_qty - ? WHERE sku = ?",
                (rl["quantity"], rl["sku"]),
            )

            unit_price_paid = prorate_unit_price(rl["unit_price"], order_discount_pct)
            line_total = unit_price_paid * rl["quantity"]
            total += line_total
            receipt_lines.append(
                {
                    "sku": rl["sku"],
                    "quantity": rl["quantity"],
                    "unit_price_paid": unit_price_paid,
                    "line_total": line_total,
                }
            )

    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "lines": receipt_lines,
        "total": total,
    }
