# Retail Store Agent

Domain model, tool layer, and CLI agent for a small retail store (clothing + general goods) with suppliers, customers, inventory, sales, returns, and promotions. Built from a raw CSV export with no prescribed schema.

## Language

**Product**:
A sellable item at the level suppliers price and cost it (e.g. `P-TEE` Classic Tee, `P-TOTE` Canvas Tote). Identified by `product_id`. Supplier cost, lead time, and promotions with `scope_type=product` all key on this.
_Avoid_: Item, SKU (see below), style

**SKU / Variant**:
One purchasable unit a cashier actually scans — a product at a specific color/size (or the product itself, if it has no variant axes, like tote/mug/socks). Identified by `sku`. Inventory (`on_hand_qty`, `reorder_point`, `reorder_qty`), sales lines, and returns all key on this — never on `product_id`.
_Avoid_: Product (too coarse), item

**Flagged (stockout flag)**:
A product is flagged per rule 7 if EITHER: (a) any one of its SKUs is at or below that SKU's own `reorder_point`, OR (b) the product's aggregate days-of-cover (on-hand summed across variants ÷ (May units sold summed across variants ÷ 30)) is under 14. Clause (a) localizes to specific SKU(s); clause (b) is a product-wide signal that doesn't point at any one variant.
_Avoid_: Low stock, low inventory (too vague about which clause tripped)

**Purchase Order (PO)**:
An invented (not in source CSVs) record of stock ordered from a supplier. Tracked **at SKU granularity** (`purchase_order_lines.sku`), not `product_id` — because `reorder_point`/`reorder_qty`, the actual "is this low" signal, live on `inventory` keyed by `sku`. `supplier_catalog` (cost, lead time) stays keyed on `product_id`, since a supplier doesn't price by color/size — a PO line's cost/lead-time is looked up via the SKU's parent `product_id`.
_Avoid_: Restock order, reorder (as a noun — "reorder" is the action, PO is the record)

**Walk-in**:
A sale or return with no associated customer (`customer_id` is null / `customer_name` omitted). Omission of a customer reference is itself the meaningful value here, not missing information — never inferred from session context.
_Avoid_: Anonymous customer, guest

## Resolved decisions worth remembering

- **Reorder generation, when a product is flagged only via the days-of-cover clause** (no SKU individually below its own `reorder_point`): still reorder every SKU of that product, each at its own `reorder_qty`. This is well-defined (not a guess) because `reorder_qty` is uniform across a product's variants in the seed data and exists per-SKU regardless of which clause tripped the flag.
- **`get_stockout_report` reports at SKU granularity**, with the product-level days-of-cover number attached as context per SKU — collapsing straight to product-level would throw away exactly the per-SKU signal `create_reorder_purchase_orders` needs to act correctly.
- **Over-return** (requested return quantity exceeds line qty minus already-returned qty): `process_return` rejects with a structured error and processes nothing. No silent partial refund.
- **Overselling** (requested sale quantity exceeds `on_hand_qty`): `create_sale` rejects the failing line with a structured error and writes nothing for it. No negative inventory, no silent partial fulfillment.
- **Sale atomicity**: a multi-line `create_sale` call is all-or-nothing. Every line is validated (SKU resolution + stock check) before anything is written; one failing line aborts the whole order.
- **Cross-turn reference fallback** (e.g. "now refund that," "make that three") only applies to arguments where the tool's own contract treats omission as *missing information* — `order_id`/`product_name` on `process_return`. It never applies to arguments where omission already has a defined business meaning, like `customer_name` on `create_sale` (see **Walk-in**) — resolving an anaphoric customer reference ("her", "Sarah") from conversation history is the model's job, not app-level session state's. The fallback fires only when the referenced argument is absent from the tool call (never overrides a supplied value) and only when exactly one unambiguous candidate exists in recent session state; otherwise it returns a clarification-needed result rather than guessing.
- **`create_promotion` resolves a `product_name` or `category` argument** (exactly one required) to `scope_type`/`scope_ref` internally, the same way `find_sku` resolves a product reference — the model never writes the literal `scope_type`/`scope_ref` strings itself. Closes off a real failure mode: "hoodie" is a product (`P-HOOD`), not the `apparel` category, and a model conflating the two would silently discount every tee and sock too.
- **Margin/revenue attribution is period-bounded, not retroactive.** A return only affects the margin/revenue of the period its own `return_date` falls in — a return processed today against a month-old sale doesn't restate that closed month's numbers. This keeps a "last month" report stable regardless of what happens later in the same session, and matches the data dictionary's "refunds issued in *that* period" phrasing for revenue kept.
- **Only a good/restocked return excludes a unit from margin.** A damaged return still refunds the customer (reduces "revenue kept"/net revenue) but leaves both the revenue and the cost of that unit counted in the margin figure — margin's carve-out is literally "returned-and-restocked," not "returned."
- **`receive_purchase_order` takes an optional `quantity_ordered`**, used only when no matching open PO exists and one must be auto-created. If given, the new PO is sized to it (partial receipt leaves the remainder open); if omitted, the new PO is sized to `quantity_received` (fully received). Needed because the tool otherwise has no way to learn an order's original total size — the human's sentence may state it, but the only quantity ever passed as a structured argument was `quantity_received`.
