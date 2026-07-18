# Limitations

Honest accounting of what this MVP does and does not do — built in ~24 hours for a hackathon demo, not production-hardened software.

## No real tool execution

AgentGuard evaluates a *proposed* action and returns a decision — it does not actually call `send_email`, `transfer_funds`, etc. against any real system. There is no execution layer wired up behind an ALLOW decision. In a production deployment, AgentGuard would sit as middleware in front of an agent's real tool-calling loop (see ARCHITECTURE.md's "Future Potential" — a real execution hook is the natural next step, not a redesign).

## Policy engine is hardcoded and English-only

The 7 demo policies in `app/policies.py` are keyword/regex-based and tuned specifically for the demo scenarios and the spec's worked example. They are:

- **Not configurable at runtime** — no admin UI, no per-organization policy packs, no way to add a policy without editing code and redeploying.
- **English-only and fairly literal** — keyword matching won't catch a paraphrase, a different language, or an obfuscated request ("send it to my personal address" without an explicit external domain may not trigger POL-002).
- **Not exhaustive** — seven policies cover the categories needed to demo all four decisions convincingly; a production system would need dozens covering the full range of tool/data combinations an agent might touch.

## Risk scoring is weight-based, not learned

Policy weights (e.g. "Credential Exposure = 55 points") were chosen by hand to produce sensible, demo-appropriate outcomes, not derived from any dataset of real incidents or calibrated against a labeled corpus. The LLM's `severity_adjustment` is bounded to ±15 specifically to prevent it from overriding this hand-tuned scoring by very much. This is a reasonable heuristic for a hackathon demo; a production system would want the weights (or a whole learned scoring model) calibrated against real historical data and reviewed by domain experts (legal/compliance/security).

## No authentication, multi-tenancy, or user identity

The FastAPI backend has no auth on any endpoint, no concept of "which user/agent/organization is making this request," and CORS is wide open (`allow_origins=["*"]`) for local demo convenience. Every evaluation is logged to a single shared SQLite file with no tenant isolation. None of this is acceptable for anything beyond a local demo.

## Single-turn, stateless evaluation

Each `/api/evaluate` call is evaluated in isolation — AgentGuard has no memory of an agent's prior actions in the same session. A sequence of individually-low-risk actions that together constitute a real problem (e.g. incrementally exfiltrating data across many small, individually-ALLOW-worthy calls) would not be caught. Session-aware / cumulative risk evaluation is future work.

## LLM reasoning quality depends on the model and is not independently benchmarked

The compliance reasoner's explanation quality, the accuracy of its `additional_risks` detection, and the sensibility of its `safe_rewritten_action` suggestions have not been evaluated against a labeled test set — they were spot-checked against the 6 demo scenarios and the spec's worked example during development. Prompt injection via the task text itself (e.g. a task engineered to manipulate the TaskAgent or ComplianceReasoner's output) was not specifically tested or hardened against.

## SQLite audit log has no retention, export, or tamper-protection

`app/db.py` appends every evaluation to a local SQLite file with no rotation, no export tooling, and no protections against the file being edited or deleted outside the app. A real audit trail for compliance purposes would need write-once storage, retention policies, and access controls.

## Offline fallback is intentionally simple

When no API key is configured (or a call fails), `agent.py`'s keyword-based `_fallback_propose_action` and `reasoner.py`'s templated explanation keep the app fully functional, but they are meaningfully less capable than the LLM path — the fallback tool-selection is a short if/elif chain, and the fallback rewrite logic (`_fallback_rewrite`) only handles one case (rerouting an external-only, non-sensitive recipient). This is a safety net for demo resilience, not a claim that the system is "just as good" without an LLM.

## No automated test suite

Verification during the build was manual: standalone scripts exercising the policy engine and pipeline end-to-end, all 6 demo scenarios run offline and checked against expected decisions, and the FastAPI routes exercised via `curl`. There is no `pytest` suite checked into the repo — for a longer-lived project this would be the first thing to add.
