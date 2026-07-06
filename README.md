# Retail Store Agent

An interactive CLI agent for a small retail store, backed by a deterministic core, a
validating tool layer, and an OpenAI tool-calling loop. See `PRD.md`, `CONTEXT.md`, and
`docs/adr/` for the full design history.

## Setup

```
pip install -r requirements.txt
```

Add your OpenAI key to `.env` (see `.env` — a `GROQ_API_KEY` may also be present from an
earlier design iteration; only `OPENAI_API_KEY` is used):

```
OPENAI_API_KEY=sk-...
```

## Start the agent

```
python -m agent.cli
```

This bootstraps a fresh in-memory database from `data/*.csv` and `schema.sql`, then opens
an interactive REPL. Type an instruction, read the reply, keep going — conversation memory
is kept for the whole session. Type `exit` to quit.

## Tests

```
python -m pytest
```
