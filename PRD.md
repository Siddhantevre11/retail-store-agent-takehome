# PRD: Retail Store Agent

## Problem Statement

A small retail store's data lives in flat CSV exports (products, customers, suppliers, inventory, orders, returns, promotions) with no schema and no tooling. Running the store — ringing up sales, processing returns, reordering stock, checking margins — currently means manually cross-referencing spreadsheets and doing discount/refund/cost arithmetic by hand, which is slow and error-prone (prorating a 10% order discount per line, remembering which supplier is cheapest *and* fast enough, knowing whether a promo was active on a given date). The store owner wants to be able to just say what they want in plain English and trust that the money and inventory numbers that come back are correct — including when their own phrasing is ambiguous, incomplete, or refers back to something said a few turns ago.

## Solution

A three-layer system: a deterministic core that implements the store's 7 business rules in pure, LLM-free Python; a tool layer that is the only code allowed to touch money or inventory (it validates input, resolves natural-language references like product names and customer names, and calls the core for all arithmetic); and a thin LLM agent that can only propose tool calls, never compute a number or pick a SKU/customer itself. The store owner starts a single CLI command and talks to the agent turn by turn, in-session memory intact, so a follow-up like "now refund that" or "make that three" resolves correctly. Every tool call is logged and printed inline so any answer can be audited without re-deriving it by hand. Wherever an instruction is genuinely ambiguous or invalid (unclear which variant, over-returning a line, overselling stock), the system asks or rejects rather than guessing — the guiding principle throughout is that the agent must be structurally incapable of getting a dollar figure wrong, even if it hallucinates.

## User Stories

### Selling

1. As a store cashier, I want to ring up a sale by describing items in natural language (product, color, size, quantity, payment method), so that I don't need to manually look up SKUs or compute prices.
2. As a store cashier, I want the agent to reject a sale line that requests more units than are currently in stock, so that I never oversell inventory or drive stock negative.
3. As a store cashier, I want a multi-item sale to either fully complete or not happen at all, so that I never end up with a partially-rung-up transaction if one line fails.
4. As a store cashier, I want any active promotion to be applied to today's price before the total is computed, so customers are automatically charged the right amount.
5. As a store cashier, I want an order-level discount to be prorated per unit and rounded to the cent (half-up), so receipts are consistent and auditable.
6. As a store cashier, I want to sell to a walk-in without a name, so I'm not forced to attach every sale to a customer record.
7. As a store cashier, I want a walk-in sale to never get silently attributed to a customer mentioned earlier in the same session, so customer records stay accurate.
8. As a store cashier, when I mention an item ambiguously (e.g. "a hoodie in medium" without a color), I want the agent to ask which variant I mean rather than guessing, so I never sell the wrong SKU.

### Returns

9. As a store cashier, I want to process a return and get back the exact amount the customer originally paid (not today's list price), so refunds are correct even if prices have since changed.
10. As a store cashier, I want the agent to refuse a return that exceeds the quantity still eligible on that line (accounting for any prior returns against it), so I can't accidentally over-refund a customer.
11. As a store cashier, I want a "good condition" return to go back into sellable stock and a "damaged" return to not, so inventory stays accurate.

### Restocking

12. As a store owner, I want to ask "what's about to stock out?" and get every SKU that's at or below its own reorder point, or whose product is below 14 days of cover in aggregate, so I know what needs attention.
13. As a store owner, I want the agent to automatically pick the cheapest supplier that can still deliver within 10 days when generating restock orders, so I don't have to manually compare supplier catalogs.
14. As a store owner, I want a purchase order to be tracked at the specific product-variant level, so that receiving stock later can unambiguously credit the correct SKU rather than guessing across a product's variants.
15. As a store owner, when a product is flagged only because its overall sales velocity is high (not because any one variant hit its reorder point), I still want every variant of that product reordered at its own reorder quantity, so restocking doesn't silently skip a flagged product.
16. As a store owner, I want to tell the agent "50 arrived from Northwind, receive them" and have it find (or, if none exists yet, correctly create) the matching purchase order, so I don't have to reference internal PO IDs.
17. As a store owner, I want a partial receipt to leave the remaining quantity open on the purchase order, so I can keep track of what's still outstanding.
18. As a store owner, when receiving stock for a multi-variant product with more than one open PO line, I want the agent to ask which variant arrived rather than guess, so on-hand counts never get silently corrupted.

### Promotions

19. As a store owner, I want to create a new promotion by naming a product or a category, not by supplying raw internal scope codes, so I can't accidentally misconfigure which items a promo applies to.
20. As a store owner, I want the system to figure out the lowest applicable price when more than one promotion could apply to the same sale, rather than stacking discounts, so pricing stays predictable.
21. As a store owner, I want a new promotion to never change the price of a sale that already happened, so historical receipts stay accurate.

### Reporting

22. As a store owner, I want to ask for the top products by profit margin last month and get an answer that already accounts for returns processed during that same month, so I can make merchandising decisions with real numbers.
23. As a store owner, I want a damaged return to still count toward that product's margin (I kept the sale but didn't recover the goods), so the margin figure reflects the true economics of a spoiled sale — only a good/restocked return should pull a unit out of margin.
24. As a store owner, I want a return processed today against a sale from a prior, already-closed period to leave that period's historical numbers unchanged, so a report I already looked at doesn't silently change later.

### Conversation & auditability

25. As a store owner, I want to refer to "that order" or "that item" in a follow-up turn without repeating myself, so the conversation feels natural.
26. As a store owner, I want the agent to act on any fully-specified, unambiguous instruction immediately rather than asking "are you sure?" first, so ringing up a sale takes one turn, not two.
27. As a store owner, I want the agent to only ask a clarifying question when a reference is genuinely ambiguous, never as a blanket confirmation ritual, so interacting with it stays efficient.
28. As a store owner, I want to start the whole system with one terminal command, so I don't need to stand up a server or web UI.
29. As a developer/grader, I want every tool call (name, arguments, result) logged and printed inline as the conversation happens, so any answer can be audited without re-deriving the numbers by hand.
30. As a developer/grader, I want session-inferred arguments (e.g. an order ID inferred from "that order") to be visibly marked as inferred in the log, distinct from arguments the model supplied explicitly, so a wrong answer's cause (model misunderstanding vs. inference logic) is traceable.

### Correctness guarantees

31. As a developer, I want every money/inventory computation (cost, discount proration, refund, margin, restock quantity, velocity) implemented in a pure, LLM-free core layer, so the agent cannot produce a wrong dollar figure even if it hallucinates.
32. As a developer, I want the tool layer to be the only code permitted to mutate money or inventory, validating and resolving references before ever calling the core, so all mutation is centrally controlled and consistent.
33. As a developer, I want the agent to never perform arithmetic or pick a SKU/customer itself — only to propose tool calls — so correctness is structurally enforced rather than depending on the model's reliability.

## Implementation Decisions

**Architecture.** Three strictly separated layers: `core/` (pure functions implementing the 7 business rules — cost, discount proration, refund, supplier selection, promotions, revenue/margin, velocity/stockout; no LLM, no I/O beyond reading values passed in), `tools/` (the only code that mutates money or inventory; validates inputs, resolves natural-language references, calls `core` for all arithmetic, returns structured results), `agent/` (an OpenAI tool-calling loop that only proposes tool calls; its system prompt is short and procedural, not a restatement of business rules).

**Schema.** SQLite, loaded ~1:1 from the CSVs: `products`, `customers`, `suppliers`, `supplier_catalog`, `inventory`, `orders`, `order_lines`, `returns`, `promotions`. Cost is looked up live from `supplier_catalog` where `supplier_id='SUP-NW'` — there is deliberately no separate product-cost table, to avoid drift. Money uses `Decimal` throughout, rounded with explicit `ROUND_HALF_UP` (not Python's built-in `round()`, which rounds half-to-even).

**Invented tables (not in the source CSVs), with one deviation from the original draft schema:** `purchase_orders(po_id, supplier_id, order_date, status)` with `status` one of `open|partial|received`, and **`purchase_order_lines` keyed on `sku`, not `product_id`** — because the actual "is this low" signal (`reorder_point`/`reorder_qty`) lives on `inventory`, which is keyed by `sku`. `supplier_catalog` stays keyed on `product_id` (a supplier's cost/lead-time don't vary by color/size); a PO line's cost and lead-time are looked up via the SKU's parent `product_id`.

**Domain glossary** (full definitions in `CONTEXT.md`): **Product** = the level suppliers price/cost at (`product_id`); **SKU/Variant** = the sellable unit inventory and sales key on (`sku`); **Flagged** = a product trips the rule-7 stockout signal via either an individual SKU's `reorder_point` breach or the product's aggregate days-of-cover; **Purchase Order** = the invented SKU-keyed restock record; **Walk-in** = an omitted customer reference, which is itself a meaningful value, not missing information.

**Tool layer — the 10 tools, with amendments from the original draft signatures:**
- `find_sku(product_name, color=None, size=None)` → a SKU, or a list of candidates on genuine ambiguity (never guesses).
- `find_customer(name)` → a customer ID or `None` (walk-in). No ambiguity handling needed — no two seed customers share a name.
- `get_unit_price(sku, as_of_date)` → list price adjusted for any promotion active on that date; lowest price wins if more than one promotion could apply.
- `create_sale(customer_name=None, lines=[...], payment_method, order_discount_pct=0, order_date)` → resolves every line (SKU + stock check) before writing anything; the whole order is atomic, so one failing line aborts the entire call rather than partially completing it; a line requesting more than `on_hand_qty` is rejected outright (no negative inventory, no partial fulfillment).
- `process_return(order_id, product_name, color=None, size=None, quantity, condition)` → reconstructs the price actually paid from the original line and order discount; rejects outright (processes nothing) if requested quantity exceeds the line's remaining eligible quantity, rather than silently capping it.
- `create_promotion(description, value_pct, start_date, end_date, product_name=None, category=None)` → exactly one of `product_name`/`category` required; the tool resolves this to `scope_type`/`scope_ref` internally (the model never writes those raw DB-column values itself, which closes off a real failure mode: "hoodie" is a product, not the `apparel` category).
- `get_stockout_report()` → reports at SKU granularity, with each SKU's parent product's aggregate days-of-cover attached as context, so the report doesn't throw away exactly the signal restocking needs.
- `create_reorder_purchase_orders(order_date)` → operates per SKU; for a product flagged only via the aggregate days-of-cover clause (no individual SKU below its own reorder point), still opens a PO line for every SKU of that product at that SKU's own `reorder_qty` — well-defined, not a guess, since `reorder_qty` is uniform per product family in the seed data.
- `receive_purchase_order(supplier_name, product_name, quantity_received, received_date, color=None, size=None, quantity_ordered=None)` → resolves to one specific SKU; if more than one open PO line exists for that product, surfaces candidates instead of guessing which variant arrived. The new `quantity_ordered` parameter is used only when no matching open PO exists and one must be auto-created — if given, the new PO is sized to it (leaving the remainder open after this receipt); if omitted, the new PO is sized to `quantity_received` (fully received).
- `get_margin_report(period='last_month', top_n=5)` → period-bounded: a return only affects the margin/revenue of the period its own `return_date` falls in, never retroactively restating an earlier, already-closed period. Only a good/restocked return excludes a unit from margin (both revenue and cost); a damaged return leaves both counted, since the store keeps the sale but not the goods.

**Cross-turn reference resolution.** Primarily handled by keeping full conversation history (including prior tool-call/tool-result content) in the messages sent to the model each turn — resolving "her"/"Sarah" from context is the model's normal job. A narrow, app-level session-state fallback exists only for arguments where the tool's own contract treats omission as *missing information* (`order_id`/`product_name` on `process_return`) — never for arguments where omission already has a defined business meaning (`customer_name` on `create_sale`, which means walk-in). The fallback only fires when an argument is absent from the tool call (never overrides a supplied value) and only when exactly one unambiguous candidate exists in recent session state (tracked: last order ID, last single SKU touched — never inferred from a multi-line order); otherwise it returns a clarification-needed result. An auto-filled argument is logged distinctly from a model-supplied one.

**Agent behavior.** System prompt is short and procedural: run the store, use the tools, never compute money or pick a SKU/customer directly, ask when a reference is genuinely ambiguous. There is no blanket "confirm before mutating" step — a fully-specified, unambiguous instruction executes immediately in one turn; the agent only pauses to ask when resolving *which* SKU/customer/PO line is genuinely ambiguous.

**LLM provider.** OpenAI `gpt-5.4-mini`, using `strict: true` JSON-schema tool definitions, so a tool call's arguments are guaranteed to validate against the schema before reaching the tool layer (see `docs/adr/0002`). This supersedes an earlier Groq/Llama-4-Scout choice (`docs/adr/0001`, kept for history).

## Testing Decisions

Good tests here check external behavior — the resulting DB state and/or the sequence of tool calls made — never implementation details or the agent's exact prose wording.

- **`tests/test_core.py`** — pure unit tests of the 7 rule functions against real seed data. Must include: O-1006 Navy-L refund == $54.00; only TOTE flagged by the stockout report on the seed data; mug restock resolves to Pioneer Goods, tote restock resolves to Northwind; at least one hand-computed margin number matches exactly. This suite gates all further work — it must be green before the tool layer is built on top of it.
- **`tests/test_tools.py`** (added seam, beyond the brief's literal checklist) — calls the 10 tools directly with explicit arguments against a fresh SQLite DB per test, no LLM involved. Exercises tool-layer validation and resolution in isolation: ambiguous `find_sku` returns candidates; over-return is rejected; oversell is rejected; multi-line sale atomicity (one bad line aborts the whole order); PO auto-create sizing with and without `quantity_ordered`; `receive_purchase_order` surfaces candidates instead of guessing across multiple open lines for one product. This is the seam that keeps failures attributable: if this suite is green but the harness fails on the same scenario, the bug is in the model's language understanding, not the tool logic.
- **`tests/harness.py`** — 40-60 self-authored adversarial prompts beyond the 10 given in the README, each run through the real agent loop (the same code path as the CLI), against an isolated fresh DB snapshot per case, with a hand-verified expected value. Grading asserts on the resulting DB state and/or tool-call sequence, never on string-matching the agent's reply text. Must cover: overlapping product+category promotions, over-returning a line, product-name synonyms, a discount and a promotion combined on the same sale, receiving against a non-existent PO, running the reorder tool when nothing is actually low, an unknown/ambiguous customer name, and multi-turn edits ("make that three" → "refund one"). Reports an aggregate pass rate.
- No seam mocks the layer beneath it: `test_tools.py` calls real `core` functions and a real (test) SQLite DB; `harness.py` calls the real tool layer and a real DB. Only the LLM call itself is the boundary being exercised at the harness seam.

## Out of Scope

- Multi-store or multi-location inventory.
- Tax computation (not present anywhere in the data dictionary or seed data).
- Authentication/authorization — this is a single local operator's CLI tool.
- A web UI or server of any kind — terminal REPL only, per the brief.
- Any LLM provider other than OpenAI (Groq and Anthropic were both considered and rejected along the way — see `docs/adr/0001` and `0002`).
- Arbitrary custom reporting periods for `get_margin_report` beyond `'last_month'` — the seed data only contains one month of order history, so a general date-range API isn't justified yet.
- Adding or editing suppliers or `supplier_catalog` entries via the agent — these are fixed reference data with no corresponding tool.
- Concurrent or multi-user sessions — a single CLI REPL with one in-memory conversation.

## Further Notes

- The organizing principle behind nearly every implementation decision above is the same one: when an instruction is ambiguous or invalid, the system rejects or asks rather than silently guessing, even where guessing would be more conversationally convenient. This was arrived at independently, several times, for different rules (overselling, over-returning, PO variant receiving, promotion scope) — it's a load-bearing pattern for the whole build, not a one-off choice.
- `CONTEXT.md` (domain glossary + resolved decisions) and `docs/adr/0001`–`0002` (LLM provider history) already exist in the repo and should be treated as living project memory — update them inline as further ambiguities surface during implementation, the same way they were built up during planning.
- The 10 sample prompts in the README are not independent test cases — several are deliberately sequenced (e.g. the two returns before the margin-report prompt) to exercise cross-rule interactions like the period-boundary rule above. Implementation and harness design should assume prompt order matters within a single grading session.
