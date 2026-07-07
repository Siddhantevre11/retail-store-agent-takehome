# Writeup

## 1. How I read the problem

The thing that shaped how I built this: the agent gets tested on 125 prompts, but I only see 10
of them. The other 115 are hidden. So the actual job isn't "make these 10 work," it's "make
something that still works on prompts I never got to look at." Those are really different
problems. If I'd tuned the code to pass the 10 samples, it wouldn't be correct, it'd just be
memorized, and it would fall over the first time a hidden prompt phrased something a little
differently.

That's why I didn't lean on the exact wording of any one sample, why I put test-first effort into
the parts that handle money and mostly thought carefully about the rest, and why I checked what
the agent actually wrote to the database instead of whether its reply sounded right. The rest of
this doc is really just those three choices playing out.

## 2. How I worked

**I looked at the actual data before I wrote any model code.** I went through the CSVs and the
data dictionary line by line before touching `tools/`. I wanted to know what each column really
meant, not just assume it from the schema. That's where the two biggest decisions came from, and
I made both before writing any `tools/` code, not after hitting a wall.

Purchase orders don't exist in the source data at all. I had to decide how to represent them from
scratch. And `reorder_point` and `reorder_qty` turned out to live on `inventory`, keyed by `sku`,
not by `product_id`. So a PO tracked at the `product_id` level would mean splitting a reorder
quantity evenly across variants, and nothing in the data justifies doing that.

**I split the build into pieces I could verify on their own, and I did the deterministic core
first.** Pricing, margin, restocking math: pure functions, no DB, no LLM involved. I got those
right and verified before building anything on top of them. That way `tools/`, and later
`agent/`, were built on money math I already knew was correct, not money math that just happened
to look right in a demo.

**I used test-first discipline where the risk was highest, and I didn't force it everywhere.**
Every rule in `core/` and `tools/`, the parts that touch money and inventory, got a failing test
before I wrote the implementation. Exploratory design questions like how ambiguous a customer
reference has to be before the agent asks, or what "flagged" should mean for a product with mixed
signals, didn't get that treatment. I worked those out by talking it through and stress-testing
scenarios first. Getting one of those wrong costs a design revision, not a wrong number in a
database. Matching the process to the risk mattered more than using one discipline for
everything.

## 3. The architecture this produced

Since correctness had to hold up on prompts I'd never see, my goal wasn't "handle the 10
samples." It was to make the LLM structurally incapable of writing a wrong number, no matter how
a request was phrased. That's what produced three layers and one mutation boundary:

```
agent/   thin OpenAI tool-calling loop: proposes tool calls, narrates results, never computes
tools/   validates + resolves references + is the ONLY code allowed to touch money or inventory
core/    pure functions (pricing, margin, restocking math), no DB, no I/O
```

![Retail agent: system architecture (block diagram)](docs/diagrams/system-design.svg)

`core/` has no side effects at all. `round_half_up`, `prorate_unit_price`, `effective_unit_price`,
`select_supplier`, `days_of_cover`, `compute_product_margins`: they all just take values in and
return values out. `tools/` is where a reference like "the navy hoodie" turns into a `sku`, where
a quantity gets checked against `on_hand_qty`, and where the actual `INSERT`/`UPDATE` happens.
`agent/` never writes SQL and never does arithmetic on money or stock.

The boundary sits right at money and inventory mutation because that's the one place a wrong LLM
decision becomes permanent and starts compounding. A hallucinated sku or a silently-clamped
quantity becomes a real row, and every later report or reorder decision trusts that row as ground
truth. Put the validation there, and the worst a bad model turn can do is ask a clarifying
question. It can never write a wrong number. That's also why `tools/`, not `agent/`, owns every
"ask instead of guess" decision. The agent can be wrong in prose for free. The tool layer can't be
wrong in a row.

## 4. How I checked it held up

An assertion harness only tells you something if it's asserting on the right thing. Mine checks
tool-call sequences and the resulting database state. It never looks at the model's prose reply.
That's on purpose: a plausible-sounding reply and a wrong database look identical from the
outside, and a test suite that just reads prose would sail right past that gap.

The clearest thing it caught: a user says "Ring up two hoodies," then "Actually make that three."
There's no `modify_sale` tool. A sale is final once it's rung up. The model didn't crash, it was
too helpful. It quietly called `create_sale` again for one more hoodie, so now there are two real
orders where the user described one edited order. Nothing about this looks wrong if you only look
at one piece: the call succeeds, the reply reads fine, inventory goes down correctly each time.
You only catch it by checking the database against what the user actually meant, which is exactly
why I built the harness that way. I fixed it by stating plainly that there's no modify or cancel
tool, and that scenario is now a permanent harness case.

The harness caught 13 more bugs the same way. A follow-up smoke run, about 80 prompts with no
known-right answer, read by hand, caught the rest. The model would silently guess a promotion's
scope instead of asking. It would crash on a hallucinated sku, on an order/sku pair that didn't
exist, or on a margin period it didn't recognize. It treated "grey" and "gray" as different
colors. It double-ordered stock when I asked it to reorder twice in a row. And it would fold a
color or size word into the product name in a way that broke a substring match, whether the word
landed in the name itself or in the wrong argument slot. I closed that one by validating against
the catalog's actual values, not a hardcoded list of words to watch for.

The best proof that a structural fix beats telling the model to behave is a number, not an
argument. The model would sometimes call `get_unit_price` with a made-up placeholder sku before
`find_sku` had resolved a real one. It usually recovered, but that was luck, not design. I
tightened the tool's own description, not the system prompt, to say plainly that `create_sale`
doesn't need it called first. That dropped `get_unit_price` calls from **29 to 3** across an
identical 82-prompt re-run: not just the 2 placeholder calls, but around 26 other speculative
"preview the price" calls the model was making out of habit. I checked this held up: **0
placeholder or unknown-sku calls** across 5 independent full re-runs, not just the one I happened
to measure.

Verifying this also forced some decisions I wouldn't have needed otherwise:

- Purchase orders are tracked at sku granularity, not `product_id`. The actual reorder signal
  lives on `inventory`, keyed by `sku`.
- Anything genuinely ambiguous (oversell, over-return, an unresolved customer, a promotion with
  no stated scope) gets rejected at the tool boundary with a structured error. It never gets
  defaulted.
- `create_sale` and `process_return` are atomic by transaction now, not just by validation
  ordering. A mid-write failure rolls back cleanly instead of relying on one never happening.
- A customer name that's stated but doesn't match anyone gets rejected, not silently treated as
  a walk-in. Walk-in means no name was given, not "a name that didn't match."
- `get_margin_report` validates its own input, separately from the tool schema. An unrecognized
  period fails cleanly no matter what the schema happens to allow.
- Cross-turn reference resolution only kicks in where a tool's own contract already treats an
  omission as missing information. It never kicks in where an omission already has a defined
  business meaning, like a walk-in sale.
- Margin is period-bounded, not retroactive, and only a good or restocked return excludes a unit
  from it. A damaged return still refunds the revenue but leaves the unit's cost counted.
- LLM choice: `gpt-5.4-mini`, specifically for `strict: true` JSON-schema tool calling. Same
  instinct as the mutation boundary, just one layer earlier: a malformed tool call should be
  structurally impossible, not just discouraged.

## 5. Honest notes + what's next

**Time-box.** This was scoped at about 2 hours. I went well past that on purpose, to stress-test
correctness against prompts beyond the 10 I was given instead of just trusting that they'd
generalize to the 115 hidden ones. In a real sprint I'd have stopped at the 41-case harness. The
smoke runs and the domain-validation work after that were depth I added to find correctness
edges, not gold-plating something that already worked.

**Stack.** I know Porter's actual stack is FastAPI, Postgres, and React/TS. I used SQLite here on
purpose, it's a zero-setup choice for a self-contained, deterministic take-home. Same relational
model (tables, foreign keys, transactions), and the schema ports to Postgres pretty much as-is.

**What's next**

- **A below-cost-sale guard.** If an order discount stacked with an active promo would sell a
  unit under its Northwind cost, the agent should warn before ringing it up. This is the exact
  kind of silent margin leak a small-business owner running this from a terminal wouldn't see in
  a spreadsheet: stack a 20% promo with a 15% loyalty discount on a thin-margin item and it can
  quietly go net-negative per unit, and nothing today would tell them. I'd build this before
  `modify_sale` below, since it protects revenue on sales that already happen correctly instead
  of fixing an edit path most sales never need.
- **A real `modify_sale`/`void_sale` tool.** Editing a completed sale is out of scope right now.
  The agent asks instead of guessing, which is correct, just not a complete answer.
- **Persistent storage across sessions.** The DB rebuilds from CSV in memory by design. A real
  deployment would want the loader to run once against a durable Postgres instance.
- **Multi-currency / multi-store support.** Everything here assumes one till, one currency, one
  supplier set. Scoping to a `store_id` and adding an FX-aware `Decimal` path is the natural next
  seam.
