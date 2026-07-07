# Writeup

## 1. Architecture: three layers, one mutation boundary

```
agent/   thin OpenAI tool-calling loop — proposes tool calls, narrates results, never computes
tools/   validates + resolves references + is the ONLY code allowed to touch money or inventory
core/    pure functions — pricing, margin, restocking math — no DB, no I/O
```

`core/` has no side effects at all: `round_half_up`, `prorate_unit_price`, `effective_unit_price`,
`select_supplier`, `days_of_cover`, `compute_product_margins` all take values in and return
values out. `tools/` is where a reference like "the navy hoodie" becomes a `sku`, where a
quantity is checked against `on_hand_qty`, and where the actual `INSERT`/`UPDATE` happens.
`agent/` never writes SQL and never does arithmetic on money or stock — it only knows how to
call a tool and relay the structured result back in prose.

The reason this boundary matters specifically at *money and inventory mutation* (not, say,
read-only reporting) is that it's the one place a wrong LLM decision becomes irreversible and
compounding: a hallucinated sku, a guessed customer, or a silently-clamped quantity turns into
a real row in `orders`/`inventory` that every subsequent report and reorder decision then
trusts as ground truth. Putting the validation there means the worst a bad model turn can do
is refuse to act or ask a clarifying question — never write a wrong number. This is also why
the tool layer, not the agent, owns every "ask instead of guess" decision in this project (see
§2) — the agent can be wrong in prose without consequence; the tool layer cannot be wrong in a
row.

## 2. Design-decisions log

These are the load-bearing decisions actually recorded in `docs/CONTEXT.md` and `docs/adr/`,
not a restatement of the brief:

- **Purchase orders are invented, and tracked at sku granularity, not product_id.** The CSVs
  have no PO table. `reorder_point`/`reorder_qty` — the actual "is this low" signal — live on
  `inventory`, keyed by `sku`. Tracking POs at `product_id` would have meant splitting a
  reorder quantity evenly across variants with no data justifying that split — a silent
  correctness bug wearing a design decision's clothes. `supplier_catalog` stays keyed on
  `product_id` (a supplier doesn't price by color/size), so a PO line's cost is looked up via
  the sku's parent product — cost-as-lookup, not cost-as-stored-fact.
- **"Flagged" is a disjunction, and the two clauses point at different granularities.**
  A product is flagged if any one sku is at/below its own `reorder_point` (points at a specific
  sku) *or* the product's aggregate days-of-cover is under 14 (a product-wide signal). When
  the flag trips only via the second clause, every sku of that product still gets reordered at
  its own `reorder_qty` — well-defined here only because `reorder_qty` is uniform across a
  product's variants in this seed data, not a general rule.
- **Ask, don't default, on genuine ambiguity — enforced at the tool boundary, not the prompt.**
  Over-return, oversell, ambiguous sku, promotion scope with neither product nor category
  stated: every one of these returns a structured error and writes nothing, rather than
  picking a plausible default. This is deliberately redundant with prompt instructions telling
  the model to ask first — the harness (§ below) is exactly what confirmed the prompt alone
  wasn't sufficient.
- **Cross-turn reference fallback is scoped narrowly.** Session-state resolution for something
  like "now refund that" only fires for arguments where the tool's own contract already treats
  omission as *missing information* (`order_id`/`product_name` on `process_return`) — never for
  `customer_name` on `create_sale`, where omission has a defined business meaning (**walk-in**,
  not "no information given"). Resolving an anaphoric customer reference ("her", "Sarah") from
  conversation history is left to the model reading its own message history, not app-level
  session state, so it can never silently overwrite a walk-in.
- **Margin/revenue attribution is period-bounded, not retroactive**, and **only a
  good/restocked return excludes a unit from margin** — a damaged return still refunds revenue
  but leaves the unit's cost counted, since the margin carve-out is "returned-and-restocked,"
  not "returned."
- **LLM choice (ADR-0002):** `gpt-5.4-mini` over flagship or nano, and over the original Groq
  choice (ADR-0001) — mid-tier cost, but the deciding factor was `strict: true` JSON-schema tool
  calling, which structurally guarantees argument shape before a call ever reaches the tool
  layer. Superseded Groq once an OpenAI key was available; the free-tier Groq rate limit
  (30 RPM/6K TPM) that ADR-0001 designed around stopped being a constraint worth keeping.

## 3. Agent-direction log

**Delegated to the agent (i.e., decided by the LLM at runtime, never hardcoded):** which tool
to call and in what order; filling tool arguments from natural language (product/customer
references, dates, quantities); resolving pronouns and cross-turn references from its own
conversation history where session state deliberately stays out of it (see the `customer_name`
carve-out above); deciding when to ask a clarifying question versus act immediately.

**Written directly, never left to the model:** every dollar and inventory computation
(`core/`), every validation and DB write (`tools/`), the narrow cross-turn fallback for
`process_return` (`agent/session.py`), and all ten tool schemas (`agent/schemas.py`) — the
model chooses *which* tool and *what arguments*, but the shape of what's askable was fixed at
design time.

**Where agent output was subtly wrong, and how it was caught:** the clearest case was a
completed-sale edit. A user says "Ring up two hoodies" and then, in the same session, "Actually
make that three." There is no `modify_sale` tool — by design, a sale is final once rung up. The
model's failure mode wasn't a crash or a refusal; it was *too helpful*: it quietly called
`create_sale` a second time for one more hoodie, producing two real orders where the user's
words describe one edited order. Nothing about this looks wrong in isolation — the tool call
succeeds, the reply reads fine, inventory decrements correctly for each call. It only surfaces
as wrong if you check DB state against user intent, which is exactly why the adversarial
harness asserts on tool-call logs and row counts rather than on the model's prose (a
`test_tools.py`-only or prose-reading test suite would never have caught this). The fix was a
system-prompt addition telling the model explicitly it has no modify/cancel tool and must ask
before ringing up a second sale for what's actually an edit — now covered by the harness case
`multiturn_edit_after_completed_sale_asks_instead_of_duplicating`.

That one bug is representative of the other ten found the same way (full list in the `tests/`
commit history) — most were the model doing something plausible-sounding that only a
DB-state/tool-log assertion would catch: silently guessing a promotion's scope, echoing a
customer_id back as if it were a name, treating "grey" and "gray" as different colors, crashing
outright on a hallucinated sku or a sku/order combination that doesn't exist, double-ordering
stock on a repeated reorder request.

**Two different failure classes, found two different ways.** The 11 harness bugs above are all
*silent-guess correctness bugs*: the model does something that looks fine but writes wrong or
duplicated state — caught by assertion-based tests because there's a known-right answer to
assert against. A separate class showed up only when I built `tests/smoke.py` and ran ~80
un-assertable prompts through the live agent for manual review (no ground truth to assert
against, just eyeballing the transcript the way a grader would): `find_sku` failed to resolve
references like "Black Tee" or "Small Tee" — the color/size adjective folded into the same
phrase as the product name — because the matcher required the whole query string to
substring-match the catalog's actual `product_name` ("Classic Tee"), regardless of whether
color/size were also passed as their own arguments. This is a *robustness gap*, not a
silent-guess bug: the failure mode was always "ask the customer to rephrase," never "sell or
return the wrong item" — the tool-boundary validation (§1) held even when the parsing upstream
of it was broken. Fixed by having `find_sku` recover a color/size word folded into the name
query (checked against the catalog's own distinct values, not a guessed word list) and use it
as the effective filter either way. Being able to tell these two classes apart — "wrote the
wrong thing" versus "correctly refused something it should have accepted" — is what determined
which test tool caught which bug; an assertion-based harness alone would never have surfaced
the second class, since there was no pre-known expected value to assert.

**A structural fix beats a behavioral instruction — measured, not claimed.** A follow-up smoke
run surfaced three more issues: the model occasionally called `get_unit_price` with an invented
placeholder sku before `find_sku` had resolved a real one; `get_margin_report` crashed with a
raw `KeyError` on any period other than `"last_month"` (the schema's `enum` only ever allowed
that one value, so a question about "this month" got silently answered with last month's
numbers, rationalized in prose); and the color/size-folding fix above needed auditing against
a nearby case (a garbage descriptor word, e.g. "Wool" passed as a color for socks). Two of
these turned out to already be correctly handled at the tool layer on inspection — `create_sale`
already resolved price internally without depending on any prior `get_unit_price` call, and the
"jumper"-style synonym resolution was already an explicit, reviewed dict, not the model
guessing — so those got audit-locking tests rather than code changes. The margin crash was a
real bug, fixed by making `"this_month"` an explicit, non-crashing unsupported-period signal
and widening the schema so the model could actually express the request instead of being
structurally forced into the wrong one.

The `get_unit_price` fix is the clearest evidence in the whole project that removing a failure
mode structurally beats instructing the model not to trigger it: after tightening the tool's
own description (not the system prompt) to state it's unnecessary before `create_sale`, a
65-conversation/82-prompt live re-run showed `get_unit_price` calls drop from **29 to 3** —
not just the 2 placeholder calls, but ~26 other speculative "preview the price" calls the model
was making out of habit. The 3 remaining calls were exactly the 3 legitimate standalone
price-lookup prompts. Confirmed stable, not a one-off: **0 placeholder/unknown-sku calls across
3 independent full re-runs (195 prompts total)**, `get_unit_price` at exactly 3 calls in all
three, and the `this_month` question correctly returning the `unsupported_period` signal in
every run.

**The mis-slotting failure class, closed in both directions.** A descriptive word can land in
the wrong place two ways: folded into `product_name` when it should have been its own argument
("Black Tee"), or a non-color/non-size word landing in the `color`/`size` argument itself
("socks" as a color, "XXL" as a size — the "Wool" case above). The first direction was fixed by
recovering a real descriptor word folded into the name query; the second is closed by
validating `color`/`size` against the catalog's actual domain (its real distinct values plus
recognized synonyms) before ever using them to filter — an invalid value is dropped rather than
filtered on, so `find_sku("Wool Socks", color="socks")` now correctly resolves to `SOCK` by name
alone instead of falsely reporting no match, while `find_sku("Tee", color="banana",
size="XXL")` still correctly surfaces all 6 candidates rather than guessing. Both directions
generalize past the specific words observed — validation is domain membership, not a table of
anticipated bad inputs — and genuine ambiguity (a bare "hoodie" or "tee" with nothing to
disambiguate it) still correctly surfaces every real candidate, never picks one. Verified across
5 total live runs of the "...a pair of Wool Socks..." scenario: resolved correctly 4 times,
asked once (before the domain-validation fix) — never sold the wrong thing in any run.

What remains structurally unfixable at the tool layer is the model confidently asserting a
specific, real, valid color/size value that doesn't actually match what the customer said at
all — pure hallucination, not mis-slotting. No amount of domain validation can distinguish a
correctly-perceived value from a confidently wrong one, since the tool only ever sees whatever
argument the model decided to pass; it has no independent access to what the customer actually
said. That's a genuine model-quality/prompting boundary, not a code defect, and the project's
explicit "ask on ambiguity, act on clarity" design (rather than confirm-before-every-mutation)
accepts it as out of scope.

**Harness result:** 41 cases, 100% pass rate, run directly against the live OpenAI API
(`python -m tests.harness`), stable across repeated reruns. 11 real silent-guess/crash bugs
found and fixed via the harness, plus 3 further robustness/crash fixes (color/size-folding,
the complementary domain-validation fix, and the margin period crash) found via the manual
smoke run, on top of 71 passing unit tests for `core/`, `tools/`, `agent/session`, and the CSV
loader.

## 4. What's next

- **A real `modify_sale`/`void_sale` tool.** Right now editing a completed sale is explicitly
  out of scope (§3) — the agent asks instead of guessing, which is correct but not a complete
  answer. A proper amend/void tool with its own atomicity and inventory-reversal rules would
  close this instead of just deflecting it.
- **Multi-currency / multi-store support.** Everything currently assumes one till, one
  currency, one set of suppliers. Scoping `inventory`/`orders` to a `store_id` and adding an
  FX-aware `Decimal` path in `core/pricing.py` would be the natural next seam.
- **Persistent storage across sessions.** The DB is rebuilt from CSV in-memory on every
  `python -m agent.cli` run by design (deterministic, disposable, good for a take-home). A real
  deployment would want the loader to run once and reopen an existing file-backed SQLite DB
  (or swap it for Postgres) so sales/returns/POs survive a restart.
- **Promotion conflict resolution beyond "lowest price wins."** Overlapping promotions
  currently resolve by taking the best price for the customer; a real store would likely want
  explicit stacking rules (e.g., category and product promos combine, or the newer promo wins)
  rather than always-lowest-price, which is a reasonable default but not the only reasonable
  policy.
