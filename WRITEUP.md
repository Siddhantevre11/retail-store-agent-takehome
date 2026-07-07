# Writeup

## 1. How I read the problem

This is a money-handling agent, and it's graded against 125 prompts — the 10 published in the
brief, and 115 more I never see. That fact *is* the problem statement, more than the brief's
feature list is. Making the 10 samples work is close to free; the real difficulty is building
something where correctness generalizes to prompts I didn't write, phrased in ways I didn't
anticipate. A design that only holds up against the prompts I happened to test isn't correct —
it's memorized.

That reframing drove almost everything below: how much weight to put on a single sample
prompt's exact phrasing, where to spend test-first discipline versus where to just think
carefully, and why verification had to assert on what the system actually *did*, not on whether
its reply sounded right.

## 2. How I worked

**Interrogated the domain against the real data before writing any model code.** I walked the
CSVs and the data dictionary line by line before touching `tools/`, asking what each column
actually meant rather than assuming from the schema. That's where the two decisions with the
most leverage came from, both made before a line of code existed rather than discovered by
hitting a wall later: purchase orders don't exist anywhere in the source data, so I had to decide
how to represent them at all — and `reorder_point`/`reorder_qty` turned out to live on
`inventory`, keyed by `sku`, not `product_id`, which meant a PO tracked at `product_id` would
require splitting a reorder quantity evenly across variants with no data justifying that split.

**Sliced the build into independently-verifiable pieces, and put the deterministic core first.**
Pricing, margin, and restocking math — pure functions, no DB, no LLM in the loop — went first and
got verified on their own, so every layer built on top of it (`tools/`, then `agent/`) was built
on money math that was already known correct, not money math that happened to look right once a
demo ran.

**Used test-first discipline where the risk was highest, and deliberately not everywhere.**
Every rule in `core/` and `tools/` — the layers that touch money and inventory — got a failing
test before its implementation. Exploratory design questions (how ambiguous a customer reference
has to be before the agent asks; what "flagged" should mean for a product with mixed signals)
didn't get that treatment — those got worked out by discussion and by stress-testing concrete
scenarios first, because getting one wrong costs a design revision, not a wrong number in a
database. Matching the process to the risk mattered more than applying one discipline
everywhere.

## 3. The architecture this produced

Because correctness had to generalize past prompts I could personally check, the design goal
wasn't "handle the 10 samples" — it was to make the LLM structurally incapable of writing a
wrong number, regardless of how a request was phrased. That goal produced three layers and one
mutation boundary:

```
agent/   thin OpenAI tool-calling loop — proposes tool calls, narrates results, never computes
tools/   validates + resolves references + is the ONLY code allowed to touch money or inventory
core/    pure functions — pricing, margin, restocking math — no DB, no I/O
```

![Retail agent: system architecture (block diagram)](docs/diagrams/system-design.svg)

`core/` has no side effects at all: `round_half_up`, `prorate_unit_price`, `effective_unit_price`,
`select_supplier`, `days_of_cover`, `compute_product_margins` all take values in and return
values out. `tools/` is where a reference like "the navy hoodie" becomes a `sku`, where a
quantity is checked against `on_hand_qty`, and where the actual `INSERT`/`UPDATE` happens.
`agent/` never writes SQL and never does arithmetic on money or stock.

The boundary sits specifically at *money and inventory mutation* because that's the one place a
wrong LLM decision becomes irreversible and compounding: a hallucinated sku or a
silently-clamped quantity becomes a real row that every later report and reorder decision then
trusts as ground truth. Putting validation there means the worst a bad model turn can do is ask
a clarifying question — never write a wrong number. It's also why `tools/`, not `agent/`, owns
every "ask instead of guess" decision — the agent can be wrong in prose for free; the tool layer
cannot be wrong in a row.

## 4. How I verified it generalizes

An assertion harness only tells you something if it asserts on the right thing. Mine asserts on
tool-call sequences and the resulting database state — never on the model's prose reply —
specifically because a plausible-sounding reply and a wrong database are indistinguishable from
the outside, and a prose-reading test suite would pass right through that gap.

![Retail agent: query flow through four layers and the mutation boundary](docs/diagrams/architecture.svg)

The clearest case it caught: a user says "Ring up two hoodies," then "Actually make that three."
There's no `modify_sale` tool — a sale is final once rung up. The model's failure mode wasn't a
crash; it was *too helpful* — it quietly called `create_sale` again for one more hoodie,
producing two real orders where the user's words describe one edited order. Nothing looks wrong
in isolation: the call succeeds, the reply reads fine, inventory decrements correctly each time.
It only surfaces if you check database state against user intent, which is exactly why the
harness is built the way it is. Fixed with an explicit statement that there's no modify/cancel
tool; the scenario is now a permanent harness case.

The harness caught 13 more the same way; a follow-up smoke run of ~80 prompts with no
known-right answer, read by hand, caught the rest — silently guessing a promotion's scope
instead of asking; crashing on a hallucinated sku, a nonexistent order/sku pairing, or an
unrecognized margin period; treating "grey" and "gray" as different colors; double-ordering
stock on a repeated reorder call; and a color/size word folded into the product name defeating a
substring match, closed in both directions — folded in, or landing directly in the wrong
argument slot — via validation against the catalog's actual values, never a hardcoded word list.

The strongest evidence that a structural fix beats a behavioral one is measured, not argued. The
model would occasionally call `get_unit_price` with an invented placeholder sku before
`find_sku` had resolved a real one — recoverable, but luck, not design. Tightening the tool's own
description — not the system prompt — to state plainly that `create_sale` doesn't need it called
first dropped `get_unit_price` calls from **29 to 3** across an identical 82-prompt re-run: not
just the 2 placeholder calls, but ~26 other speculative "preview the price" calls the model made
out of habit. Confirmed stable across 5 independent full re-runs, not a one-off: **0
placeholder/unknown-sku calls** in any of them.

Verification also forced decisions the design wouldn't have needed otherwise:

- Purchase orders track at sku granularity, not `product_id` — the actual reorder signal lives
  on `inventory`, keyed by `sku`.
- Every genuinely ambiguous case — oversell, over-return, an unresolved customer, a promotion
  with no stated scope — is rejected at the tool boundary with a structured error, never
  defaulted.
- `create_sale`/`process_return` are atomic by transaction, not by validation ordering — a
  mid-write failure now rolls back cleanly instead of relying on there never being one.
- An unresolved-but-stated customer name is rejected, not silently treated as a walk-in —
  walk-in means no name was given, not "a name that didn't match."
- `get_margin_report` validates its own input independently of the tool schema, so an
  unrecognized period fails cleanly regardless of what the schema happens to allow.
- Cross-turn reference resolution only fires where a tool's own contract already treats
  omission as missing information — never where omission has a defined business meaning of its
  own, like a walk-in sale.
- Margin is period-bounded, not retroactive, and only a good/restocked return excludes a unit
  from it — a damaged return still refunds revenue but leaves the unit's cost counted.
- LLM choice: `gpt-5.4-mini`, specifically for `strict: true` JSON-schema tool calling — the same
  instinct as the mutation boundary, applied one layer earlier: a malformed tool call should be
  structurally impossible, not just discouraged.

## 5. Honest notes + what's next

**Time-box.** This was scoped at ~2 hours; I went well past that deliberately, to stress
correctness against prompts beyond the given 10 rather than trust that 10 samples generalize to
the 115 hidden ones. In a real sprint I'd have stopped at the 41-case harness — the smoke runs
and the domain-validation generalization were depth added to surface correctness edges, not
gold-plating an already-passing feature.

**Stack.** I know Porter's actual stack is FastAPI + Postgres + React/TS. SQLite here was a
deliberate zero-setup choice for a self-contained, deterministic take-home — same relational
model (tables, foreign keys, transactions), and the schema ports to Postgres largely as-is.

**What's next**

- **A below-cost-sale guard.** When an order discount stacked with an active promo would sell a
  unit under its Northwind cost, the agent should warn before ringing it up. This is the exact
  silent margin leak a small-business owner running this from a terminal can't see in a
  spreadsheet — a stacked 20% promo and a 15% loyalty discount on a thin-margin item can quietly
  go net-negative per unit, and nothing today would tell them. Worth building before
  `modify_sale` below — it protects revenue on sales that already happen correctly, rather than
  fixing an edit path most sales never need.
- **A real `modify_sale`/`void_sale` tool** — editing a completed sale is explicitly out of scope
  today; the agent asks instead of guessing, correct but not complete.
- **Persistent storage across sessions** — the DB rebuilds from CSV in-memory by design; a real
  deployment wants the loader to run once against a durable Postgres instance.
- **Multi-currency / multi-store support** — everything assumes one till, one currency, one
  supplier set; scoping to a `store_id` and an FX-aware `Decimal` path is the natural next seam.
