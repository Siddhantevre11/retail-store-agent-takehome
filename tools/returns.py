from decimal import Decimal

from core.pricing import prorate_unit_price
from tools.ids import next_sequential_id
from tools.sales import find_sku


def _next_return_id(conn):
    return next_sequential_id(conn, "returns", "return_id", "R", start=2000)


def process_return(
    conn, order_id, product_name, quantity, condition, return_date, color=None, size=None
):
    """Rule 3: refund the price actually paid; good returns restock, damaged don't.

    Rejects outright — no return row inserted, no refund, no restock — if the
    requested quantity exceeds the line's remaining eligible quantity.
    """
    sku = find_sku(conn, product_name, color=color, size=size)
    if not isinstance(sku, str):
        return {"error": "ambiguous_sku", "product_name": product_name, "candidates": sku}

    line = conn.execute(
        "SELECT quantity, unit_price FROM order_lines WHERE order_id = ? AND sku = ?",
        (order_id, sku),
    ).fetchone()
    if line is None:
        return {"error": "sku_not_on_order", "order_id": order_id, "sku": sku}

    already_returned = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS n FROM returns WHERE order_id = ? AND sku = ?",
        (order_id, sku),
    ).fetchone()["n"]

    remaining_eligible = line["quantity"] - already_returned
    if quantity > remaining_eligible:
        return {
            "error": "over_return",
            "sku": sku,
            "requested": quantity,
            "remaining_eligible": remaining_eligible,
        }

    order = conn.execute(
        "SELECT order_discount_pct FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    unit_price_paid = prorate_unit_price(
        Decimal(line["unit_price"]), Decimal(order["order_discount_pct"])
    )
    refund_amount = unit_price_paid * quantity

    return_id = _next_return_id(conn)
    # Atomic by transaction: `with conn` rolls back both the return INSERT
    # and the inventory UPDATE together on any exception, rather than
    # risking a refund recorded with stock never actually restocked.
    with conn:
        conn.execute(
            "INSERT INTO returns (return_id, return_date, order_id, sku, quantity, condition, refund_amount)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (return_id, return_date.isoformat(), order_id, sku, quantity, condition, str(refund_amount)),
        )

        if condition == "good":
            conn.execute(
                "UPDATE inventory SET on_hand_qty = on_hand_qty + ? WHERE sku = ?", (quantity, sku)
            )

    return {
        "return_id": return_id,
        "sku": sku,
        "quantity": quantity,
        "condition": condition,
        "refund_amount": refund_amount,
    }
