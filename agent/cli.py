import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from agent.loop import run_agent_turn
from db.loader import bootstrap_db
from tools.promotions import create_promotion
from tools.restocking import get_stockout_report
from tools.returns import process_return
from tools.sales import create_sale, find_customer, find_sku, get_unit_price

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL = "gpt-5.4-mini"

SYSTEM_PROMPT = (
    "You run a small retail store. You have tools to look up products, customers, "
    "and prices, and to ring up sales. Always use a tool to resolve a product, "
    "customer, or price — never guess or compute one yourself. If a tool reports "
    "genuine ambiguity (e.g. multiple product candidates) or a validation error "
    "(e.g. insufficient stock), tell the user and ask what they'd like to do — "
    "never retry with a guess. Otherwise, act on a clear instruction immediately "
    "and report the result; don't ask for confirmation first. Today's date is "
    "2026-06-19 unless the user states another date."
)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_sku",
            "description": (
                "Resolve a product reference to a sku. Returns {'sku': ...} if "
                "unambiguous, or {'candidates': [...]} if more than one variant matches."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "color": {"type": ["string", "null"]},
                    "size": {"type": ["string", "null"]},
                },
                "required": ["product_name", "color", "size"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_customer",
            "description": "Resolve a customer name to a customer_id, or null for a walk-in/unknown name.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_price",
            "description": "Get the promo-adjusted unit price for a sku as of a given date (YYYY-MM-DD).",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "as_of_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["sku", "as_of_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_sale",
            "description": (
                "Ring up a sale. Atomic across all lines — resolves and stock-checks "
                "every line before writing anything; rejects the whole sale with a "
                "structured error if any line is ambiguous or exceeds on-hand stock."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": ["string", "null"],
                        "description": "Omit (null) for a walk-in — never infer a customer.",
                    },
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_name": {"type": "string"},
                                "color": {"type": ["string", "null"]},
                                "size": {"type": ["string", "null"]},
                                "quantity": {"type": "integer"},
                            },
                            "required": ["product_name", "color", "size", "quantity"],
                            "additionalProperties": False,
                        },
                    },
                    "payment_method": {"type": "string", "enum": ["cash", "card"]},
                    "order_discount_pct": {
                        "type": "string",
                        "description": "Whole-order discount percent, e.g. '10' for 10%. '0' if none stated.",
                    },
                    "order_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": [
                    "customer_name",
                    "lines",
                    "payment_method",
                    "order_discount_pct",
                    "order_date",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_return",
            "description": (
                "Process a return against an existing order. Refunds the price actually "
                "paid (not today's price). Rejects with a structured error if the "
                "requested quantity exceeds what's still eligible on that line — never "
                "partially fulfills. Good condition restocks; damaged does not."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "product_name": {"type": "string"},
                    "color": {"type": ["string", "null"]},
                    "size": {"type": ["string", "null"]},
                    "quantity": {"type": "integer"},
                    "condition": {"type": "string", "enum": ["good", "damaged"]},
                    "return_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": [
                    "order_id",
                    "product_name",
                    "color",
                    "size",
                    "quantity",
                    "condition",
                    "return_date",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_promotion",
            "description": (
                "Create a percent-off promotion, scoped to exactly one of product_name "
                "or category — never both, never neither. Resolves the scope internally; "
                "you never choose category as a stand-in for a specific product (e.g. a "
                "hoodie-only sale must use product_name='hoodie', not category='apparel', "
                "which would also discount tees/socks)."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "value_pct": {"type": "string", "description": "e.g. '20' for 20% off"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "product_name": {"type": ["string", "null"]},
                    "category": {"type": ["string", "null"], "description": "'apparel' or 'goods'"},
                },
                "required": [
                    "description",
                    "value_pct",
                    "start_date",
                    "end_date",
                    "product_name",
                    "category",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stockout_report",
            "description": (
                "List every sku that's about to stock out — either below its own "
                "reorder point, or its product's aggregate days-of-cover is under 14."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


def _build_tool_registry(conn):
    def _find_sku(product_name, color, size):
        result = find_sku(conn, product_name, color=color, size=size)
        if isinstance(result, str):
            return {"sku": result}
        return {"candidates": result}

    def _find_customer(name):
        return {"customer_id": find_customer(conn, name)}

    def _get_unit_price(sku, as_of_date):
        return {"unit_price": str(get_unit_price(conn, sku, date.fromisoformat(as_of_date)))}

    def _create_sale(customer_name, lines, payment_method, order_discount_pct, order_date):
        return create_sale(
            conn,
            lines=lines,
            payment_method=payment_method,
            order_date=date.fromisoformat(order_date),
            customer_name=customer_name,
            order_discount_pct=Decimal(order_discount_pct),
        )

    def _process_return(order_id, product_name, color, size, quantity, condition, return_date):
        return process_return(
            conn,
            order_id=order_id,
            product_name=product_name,
            color=color,
            size=size,
            quantity=quantity,
            condition=condition,
            return_date=date.fromisoformat(return_date),
        )

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

    return {
        "find_sku": _find_sku,
        "find_customer": _find_customer,
        "get_unit_price": _get_unit_price,
        "create_sale": _create_sale,
        "process_return": _process_return,
        "create_promotion": _create_promotion,
        "get_stockout_report": _get_stockout_report,
    }


def _log_tool_call(name, args, result):
    print(f"  [tool] {name}({args}) -> {result}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    conn = bootstrap_db(DATA_DIR)
    tool_registry = _build_tool_registry(conn)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("Retail Store Agent. Type an instruction, or 'exit' to quit.")
    while True:
        user_input = input("> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break

        messages.append({"role": "user", "content": user_input})
        messages, reply = run_agent_turn(
            client, MODEL, messages, tool_registry, TOOL_SCHEMAS, log_fn=_log_tool_call
        )
        print(reply)


if __name__ == "__main__":
    main()
