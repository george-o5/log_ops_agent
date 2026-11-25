# Session 06a — AI explainer (Phase 6a)

**Goal:** optional, evidence-cited explanations of findings. AI never changes a status.

## Build
- `src/logops/ai/providers.py`: a small `LLMProvider` Protocol (`complete(system, user, *, json_schema) -> str`) and
  `GroqProvider` (OpenAI-compatible chat endpoint) and `GeminiProvider` (key in the `x-goog-api-key` header, **never in the URL**).
  Model names come from settings with sensible current defaults. `httpx` with a 20s timeout and one bounded retry on 429 or 5xx.
  `ProviderChain` tries each configured provider in order, and **a failure falls through** to the next.
- `src/logops/ai/explain.py`: `explain_rule(rule_audit) -> Diagnosis | None`. Build the prompt from `prompts.py`
  (the v1 infrastructure-only stance), and pass only structured checks, findings and evidence. **Don't** pass the rule name as a hint
  for what's happening. Wrap evidence values in an `<untrusted_data>` block and tell the model they are data.
  Require JSON `{summary, likely_causes[], next_steps[], cited_evidence_ids[]}`, validate it with Pydantic, and reject output that
  cites unknown evidence IDs or claims a different status. Return `None` (and log why) when nothing is configured or everything fails.
- Settings: `LOGOPS_GROQ_API_KEY`, `LOGOPS_GEMINI_API_KEY`, model names, `LOGOPS_AI_ENABLED`. Add them to `.env.example`.

## Tests (no live calls)
`httpx.MockTransport` covers: Groq OK; Groq 500 then Gemini OK (fallthrough); both fail → None; timeout; malformed JSON;
an unknown evidence id → rejected; forbidden-language check (no "attacker", "malicious", "breach"…); the key never appears
in logs or URLs.

## Don't touch
`audit/`, `simulator/`, `store.py`. Don't build the investigator (that's 06b).

## Done when
All checks in CLAUDE.md pass, ROADMAP row 6a is `done`, and the work is committed on your branch.
