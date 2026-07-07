SYSTEM_PROMPT = (
    "You run a small retail store. You have tools to look up products, customers, "
    "and prices, and to ring up sales. Always use a tool to resolve a product, "
    "customer, or price — never guess or compute one yourself. If a tool reports "
    "genuine ambiguity (e.g. multiple product candidates) or a validation error "
    "(e.g. insufficient stock), tell the user and ask what they'd like to do — "
    "never retry with a guess. Otherwise, act on a clear instruction immediately "
    "and report the result; don't ask for confirmation first. Today's date is "
    "2026-06-19 unless the user states another date.\n\n"
    "You have no tool to modify or cancel a completed order — every sale, once "
    "rung up, is final. If a follow-up refers to changing the quantity or "
    "contents of a sale you already completed (e.g. 'make that three', 'actually "
    "add one more to that'), do not silently ring up a second full sale — ask the "
    "customer to clarify what they'd like (e.g. an additional line for the "
    "difference, or a return of the original followed by a new sale)."
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
            "description": (
                "Resolve a customer name to a customer_id. Returns null customer_id only "
                "when name is empty/not stated (a walk-in). If a name WAS given but doesn't "
                "match a real customer, or matches more than one, returns "
                "{'candidates': [...]} instead (empty list if no match) — this is not a "
                "walk-in, ask the user to confirm the customer rather than proceeding."
            ),
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
            "description": (
                "Get the promo-adjusted unit price for a sku as of a given date "
                "(YYYY-MM-DD), for a standalone price lookup (e.g. 'what does this cost'). "
                "The sku must be one already returned by find_sku — never an invented or "
                "placeholder value. Not needed before create_sale: create_sale resolves "
                "each line's price internally from its own resolved sku."
            ),
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
                        "description": (
                            "Omit (null) for a walk-in — never infer a customer. A stated "
                            "name that doesn't match a real customer is rejected with an "
                            "unknown_customer error (nothing gets rung up as a walk-in) — "
                            "confirm the customer with the user rather than retrying blind."
                        ),
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
                "partially fulfills. Good condition restocks; damaged does not. Omit "
                "order_id/product_name (null) only if genuinely not stated in this turn "
                "and clearly implied by the immediately preceding single-item sale — "
                "otherwise always supply them explicitly."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": ["string", "null"]},
                    "product_name": {"type": ["string", "null"]},
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
                "which would also discount tees/socks). If the user didn't state which "
                "product or category the promotion applies to, do not call this tool with "
                "a guessed scope — ask them which one they mean first."
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
    {
        "type": "function",
        "function": {
            "name": "create_reorder_purchase_orders",
            "description": (
                "Open purchase orders for everything currently flagged as about to "
                "stock out, from the cheapest supplier that can deliver within 10 days."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"order_date": {"type": "string", "description": "YYYY-MM-DD"}},
                "required": ["order_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "receive_purchase_order",
            "description": (
                "Receive stock against an open/partial purchase order for a supplier+"
                "product, or auto-create one if none exists yet. Surfaces candidates "
                "instead of guessing if the product reference is ambiguous."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_name": {"type": "string"},
                    "product_name": {"type": "string"},
                    "color": {"type": ["string", "null"]},
                    "size": {"type": ["string", "null"]},
                    "quantity_received": {"type": "integer"},
                    "received_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "quantity_ordered": {
                        "type": ["integer", "null"],
                        "description": (
                            "The order's original total size, only if the user stated one "
                            "(e.g. 'a PO for 50 is open'). Only used if no PO exists yet."
                        ),
                    },
                },
                "required": [
                    "supplier_name",
                    "product_name",
                    "color",
                    "size",
                    "quantity_received",
                    "received_date",
                    "quantity_ordered",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_margin_report",
            "description": (
                "Top products by profit margin for a period. Period-bounded: a "
                "return only affects the margin of the period its own return date "
                "falls in. Only good/restocked returns reduce margin; damaged "
                "returns don't. 'this_month' is a recognized but unsupported period — "
                "the current month is still in progress, so pass it through as-is and "
                "surface the resulting unsupported_period error rather than "
                "substituting last_month."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["last_month", "this_month"]},
                    "top_n": {"type": "integer"},
                },
                "required": ["period", "top_n"],
                "additionalProperties": False,
            },
        },
    },
]
