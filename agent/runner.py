from datetime import date
from decimal import Decimal
from pathlib import Path

from agent.loop import run_agent_turn
from agent.schemas import SYSTEM_PROMPT, TOOL_SCHEMAS
from agent.session import SessionState, resolve_return_reference
from db.loader import bootstrap_db
from tools.margin import get_margin_report
from tools.promotions import create_promotion
from tools.purchase_orders import create_reorder_purchase_orders, receive_purchase_order
from tools.restocking import get_stockout_report
from tools.returns import process_return
from tools.sales import create_sale, find_customer, find_sku, get_unit_price

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL = "gpt-5.4-mini"


def build_tool_registry(conn, session):
    def _find_sku(product_name, color, size):
        result = find_sku(conn, product_name, color=color, size=size)
        if isinstance(result, str):
            return {"sku": result}
        return {"candidates": result}

    def _find_customer(name):
        return {"customer_id": find_customer(conn, name)}

    def _get_unit_price(sku, as_of_date):
        result = get_unit_price(conn, sku, date.fromisoformat(as_of_date))
        if isinstance(result, dict):  # {"error": "unknown_sku", ...}
            return result
        return {"unit_price": str(result)}

    def _create_sale(customer_name, lines, payment_method, order_discount_pct, order_date):
        result = create_sale(
            conn,
            lines=lines,
            payment_method=payment_method,
            order_date=date.fromisoformat(order_date),
            customer_name=customer_name,
            order_discount_pct=Decimal(order_discount_pct),
        )
        if "order_id" in result:
            session.record_sale(order_id=result["order_id"], lines=lines)
        return result

    def _process_return(order_id, product_name, color, size, quantity, condition, return_date):
        resolved = resolve_return_reference(session, order_id, product_name, color, size)
        if resolved is None:
            return {
                "error": "ambiguous_reference",
                "message": "Which order/item do you mean? Please specify.",
            }

        result = process_return(
            conn,
            order_id=resolved["order_id"],
            product_name=resolved["product_name"],
            color=resolved["color"],
            size=resolved["size"],
            quantity=quantity,
            condition=condition,
            return_date=date.fromisoformat(return_date),
        )
        if resolved["inferred"]:
            result = dict(result)
            result["inferred_fields"] = {
                "order_id": resolved["order_id"],
                "product_name": resolved["product_name"],
            }
        return result

    def _create_promotion(description, value_pct, start_date, end_date, product_name, category):
        return create_promotion(
            conn,
            description=description,
            value_pct=Decimal(value_pct),
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            product_name=product_name,
            category=category,
        )

    def _get_stockout_report():
        return get_stockout_report(conn)

    def _create_reorder_purchase_orders(order_date):
        return create_reorder_purchase_orders(conn, order_date=date.fromisoformat(order_date))

    def _receive_purchase_order(
        supplier_name, product_name, color, size, quantity_received, received_date, quantity_ordered
    ):
        return receive_purchase_order(
            conn,
            supplier_name=supplier_name,
            product_name=product_name,
            color=color,
            size=size,
            quantity_received=quantity_received,
            received_date=date.fromisoformat(received_date),
            quantity_ordered=quantity_ordered,
        )

    def _get_margin_report(period, top_n):
        return get_margin_report(conn, period=period, top_n=top_n)

    return {
        "find_sku": _find_sku,
        "find_customer": _find_customer,
        "get_unit_price": _get_unit_price,
        "create_sale": _create_sale,
        "process_return": _process_return,
        "create_promotion": _create_promotion,
        "get_stockout_report": _get_stockout_report,
        "create_reorder_purchase_orders": _create_reorder_purchase_orders,
        "receive_purchase_order": _receive_purchase_order,
        "get_margin_report": _get_margin_report,
    }


def run_conversation(client, prompts, data_dir=DATA_DIR, log_fn=None):
    """Bootstrap a fresh DB, run each prompt through the real agent loop in
    sequence, and return (conn, session, tool_log, replies) for inspection —
    the harness's seam for asserting on DB state / tool-call sequence rather
    than the model's prose.
    """
    conn = bootstrap_db(data_dir)
    session = SessionState()
    tool_registry = build_tool_registry(conn, session)
    tool_log = []

    def _record(name, args, result):
        tool_log.append((name, args, result))
        if log_fn:
            log_fn(name, args, result)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    replies = []
    for prompt in prompts:
        messages.append({"role": "user", "content": prompt})
        messages, reply = run_agent_turn(
            client, MODEL, messages, tool_registry, TOOL_SCHEMAS, log_fn=_record
        )
        replies.append(reply)

    return conn, session, tool_log, replies
