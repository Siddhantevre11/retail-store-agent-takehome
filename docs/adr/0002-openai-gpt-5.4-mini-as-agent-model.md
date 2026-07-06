# Use OpenAI gpt-5.4-mini as the agent's LLM, superseding Groq (ADR-0001)

Superseded ADR-0001 (Groq + Llama 4 Scout) once the user had an OpenAI API key available and preferred it. Landed on `gpt-5.4-mini` over flagship (`gpt-5.4`/`gpt-5.5`) or `gpt-5.4-nano`: mid-tier cost ($0.75/M input, $4.50/M output) with strong tool-calling reliability, which is what this agent actually needs — the model's whole job is picking the right tool and filling arguments correctly, never computing money itself.

The concrete win over Groq/Llama: OpenAI's `strict: true` JSON schema mode on tool definitions guarantees a tool call's arguments validate against the schema exactly (correct types, all required fields present) before it ever reaches the tool layer — closing off a class of malformed-tool-call failures a smaller open model couldn't structurally guarantee. Also drops the free-tier rate-limit constraint (30 RPM/6K TPM on Groq) that ADR-0001 had to design around.
