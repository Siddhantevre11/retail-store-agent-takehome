---
status: superseded by ADR-0002
---

# Use Groq + Llama 4 Scout as the agent's LLM, not Anthropic Claude

The build brief (and the README's stack section, which explicitly allows "any LLM with tool calling") originally assumed Anthropic API tool calling. We're using Groq instead, at the user's request, on a cost basis (no paid API spend).

Within Groq, we rejected `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` — both were announced deprecated by Groq on 2026-06-17, three weeks before this project started, with no published shutdown date. We landed on `meta-llama/llama-4-scout-17b-16e-instruct`: current (not on the deprecation list), free-tier eligible, and supports tool calling. Its free tier is rate-limited to 30 RPM / 6K TPM / 1K requests per day, which the agent loop and test harness need to respect (retry-with-backoff on 429s) — this is the main downstream consequence of the choice.

Rejected `openai/gpt-oss-120b` / `gpt-oss-20b` (Groq's own suggested migration targets off the deprecated Llama models) and `llama-4-maverick` (stronger, but free tier gives it roughly half the daily request allowance) to stay on a free, current, Llama-family model.
