# Architecture

## Pipeline overview

```
User (Streamlit)
   │  POST task
   ▼
FastAPI /api/evaluate
   │
   ▼
AgentGuard.process_task(task)          [app/guard.py]
   │
   ├─► TaskAgent.propose_action(task)  [app/agent.py]
   │        │
   │        ├─ LLM path: Claude Sonnet 5, structured output (ProposedAction schema)
   │        └─ Fallback: keyword-based tool/sensitivity guesser (no LLM needed)
   │        ▼
   │   ProposedAction { tool_name, action, parameters, data_sensitivity, reasoning }
   │
   ├─► ComplianceReasoner.evaluate(task, action)  [app/reasoner.py]
   │        │
   │        ├─ PolicyEngine.evaluate(action)  [app/policies.py]
   │        │      → runs 7 deterministic detectors (regex/keyword)
   │        │      → detected_risks, violated_policies, base_risk_score (0-100)
   │        │
   │        ├─ LLM assessment (if API key configured):
   │        │      Claude Sonnet 5 given the action + policy signals, asked for:
   │        │        - explanation (plain language, specific)
   │        │        - additional_risks (anything the rules missed)
   │        │        - severity_adjustment (-15..+15, bounded)
   │        │        - safe_rewritten_action (if the risk is remediable)
   │        │      NOTE: the LLM never outputs the final decision.
   │        │
   │        ├─ risk_score = clamp(base_risk_score + severity_adjustment, 0, 100)
   │        ├─ decision = f(risk_score, has_rewrite)   [fixed thresholds, pure code]
   │        │
   │        ▼
   │   EvaluationResult { decision, risk_score, detected_risks, violated_policies,
   │                       explanation, safe_rewritten_action, reasoning_source }
   │
   └─► db.log_evaluation(result)  [app/db.py, SQLite]
   ▼
Response → Streamlit renders decision badge, risk gauge, risks, policies,
           explanation, rewrite diff, and audit history
```

## Why the LLM doesn't make the final decision

Two LLM calls happen per evaluation: one to turn the natural-language task into a structured `ProposedAction` (the "AI agent" being guarded), and one to reason about that action's risk (the "compliance reasoner"). Both use Claude's **structured outputs** (`output_config.format` / `client.messages.parse`) so every response is a validated Pydantic model — no manual JSON parsing, no risk of a malformed response breaking the pipeline.

The compliance reasoner's LLM call is deliberately scoped to **explanation and severity refinement only** — it cannot choose ALLOW/BLOCK/REWRITE/REQUIRE_APPROVAL directly. That mapping is `_decide()` in `reasoner.py`, a pure function of the final risk score:

| Risk score | Decision |
|---|---|
| ≥ 75 | BLOCK |
| 50–74 | REQUIRE_APPROVAL |
| 25–49 (with a safe rewrite available) | REWRITE |
| 25–49 (no safe rewrite available) | REQUIRE_APPROVAL |
| < 25 | ALLOW |

This split exists for two reasons:

1. **Reproducibility.** The same action should get the same decision every time (module cache effects and rare boundary-adjacent LLM refinements aside) — important for a live demo where judges expect consistent behavior, and for compliance systems generally where non-determinism is a liability.
2. **Graceful degradation.** If `ANTHROPIC_API_KEY` is unset or the API call fails for any reason, `llm_client.structured_call()` catches the exception and returns `None` — both `agent.py` and `reasoner.py` have keyword-based fallback paths, so the *entire pipeline still produces a complete, correctly-shaped `EvaluationResult`* using the policy engine alone. This was validated: all 6 demo scenarios produce their intended decision with `ANTHROPIC_API_KEY` unset.

## Component responsibilities

| File | Responsibility | Talks to LLM? |
|---|---|---|
| `schemas.py` | Single source of truth for data shapes (`ProposedAction`, `EvaluationResult`, `Decision`, etc.) | No |
| `policies.py` | 7 hardcoded demo policies + `PolicyEngine` that runs keyword/regex detectors against an action | No |
| `config.py` | Reads `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, DB path, API URL from env/`.env` | No |
| `llm_client.py` | Thin `AsyncAnthropic` wrapper; owns model choice, structured-output parsing, and turning any failure into `None` | Yes (only module that imports the SDK) |
| `agent.py` | `TaskAgent`: NL task → `ProposedAction`, with a keyword-based offline fallback | Yes, via `llm_client` |
| `reasoner.py` | `ComplianceReasoner`: runs `PolicyEngine`, optionally calls the LLM for explanation/severity/rewrite, computes the final decision | Yes, via `llm_client` |
| `db.py` | SQLite audit log (stdlib `sqlite3`, no ORM) | No |
| `scenarios.py` | 6 fixed demo tasks with their expected decisions | No |
| `guard.py` | `AgentGuard`: orchestrates agent → reasoner → db logging; the single entry point | No (delegates) |
| `main.py` | FastAPI routes (`/api/evaluate`, `/api/scenarios`, `/api/history`, `/api/health`) | No (delegates) |
| `streamlit_app.py` | Dashboard UI; talks to the backend only over HTTP via `httpx` | No (delegates via API) |

## Data flow contract

`ProposedAction` and `EvaluationResult` (`app/schemas.py`) are the two contracts that flow through the entire system — from the LLM's structured output, through the policy engine, into SQLite, out through the FastAPI response model, into the Streamlit UI. Because they're Pydantic models used everywhere (not re-declared per layer), a schema change in one place is enforced everywhere else automatically, and FastAPI derives its OpenAPI schema and request/response validation directly from them.

## Async design

`agent.py`, `reasoner.py`, `llm_client.py`, `guard.py`, and every route in `main.py` are `async def` — the two LLM calls per evaluation (agent + reasoner) are the only I/O-bound work in the request, and using `AsyncAnthropic` means the FastAPI event loop isn't blocked waiting on the network during a call, so the server can still serve `/api/health` or `/api/history` concurrently with an in-flight `/api/evaluate`.
