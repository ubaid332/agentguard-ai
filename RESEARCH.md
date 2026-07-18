# Research & Design Rationale

Notes on the key decisions behind AgentGuard's design, for judges asking "why did you build it this way?" and for the primary developer to be able to defend every choice.

## Why intercept before execution, not review logs after

Most "AI safety" tooling in production today is observability: log what the agent did, alert on anomalies after the fact. That's forensics, not prevention — by the time you see the log entry, the email already sent. AgentGuard's core premise is that a **safety layer only has value if it sits in the critical path**, between the agent deciding what to do and the tool actually running. This is why the architecture has a hard `AgentGuard Interceptor` step between `AI Agent` and `Tool Execution` in the pipeline, rather than a background auditor. In this MVP, "tool execution" is simulated (the point is the interception + decision, not building 8 real integrations in 24 hours) — see LIMITATIONS.md.

## Why a hybrid policy-engine + LLM design, not "just ask the LLM"

The obvious hackathon shortcut is: give an LLM the action and a prompt describing your policies, ask it for JSON back with a decision. We considered this and rejected it as the *primary* mechanism for three reasons:

1. **Non-determinism is a liability for compliance.** A system whose BLOCK/ALLOW verdict can flip between two calls on the identical input is hard to trust and hard to demo reliably — a judge re-running the same scenario twice should not get different results.
2. **No graceful degradation.** If the LLM call is the entire decision mechanism and it fails (rate limit, network blip, missing key), the system either throws an error or has to fall back to *some* other logic anyway — so you end up building the rule-based path regardless. We built it first and made it the foundation.
3. **Auditability.** "The model decided X" is a much weaker compliance story than "policy POL-002 (External Data Transfer) was violated, contributing 35 risk points, pushing the total to 75, which crosses the BLOCK threshold." Regulators and security reviewers want the second kind of explanation.

So the design inverts the obvious approach: **deterministic rules compute the risk signal and the decision; the LLM's job is understanding language and explaining/refining, not deciding.** This is a common pattern in real fraud/risk systems (rules engine + ML/LLM-assisted review), not something invented for this hackathon — see below.

## Why structured outputs instead of prompt-and-parse

Early LLM-integration code often does `response = llm(prompt)` then regex/`json.loads()` the text out of a chat response, with a `try/except` around the parse. This is fragile — free-form generation can wrap JSON in markdown fences, add a preamble, or produce nearly-but-not-quite-valid JSON. AgentGuard uses Claude's **structured outputs** feature (`output_config.format` under the hood, exposed via `client.messages.parse(output_format=PydanticModel)`) for both LLM calls, so the SDK validates the response against the Pydantic schema and either returns a correctly-typed object or the parse fails cleanly — which we treat as "LLM unavailable" and fall through to the deterministic path, rather than crashing.

## Why the risk score is `base_score + bounded_adjustment`, not two independent scores averaged

We considered letting the LLM produce its own 0-100 risk score directly and blending it with the policy engine's score (e.g. average, or max). We rejected this because an LLM asked "give this a risk score" tends to anchor on vague intuitions ("this feels like a 70") that aren't tied to any of the specific policies, making the number hard to justify. Instead, the LLM contributes a **small bounded adjustment (-15 to +15)** to the policy engine's score — explicitly framed as "the rule engine's flat keyword weighting might over/understate this specific case's severity." This keeps the score anchored to explicit policy violations while still letting the LLM's contextual understanding matter (e.g. recognizing that "$1,000" in a test-fixture context is different from "$1,000" in a live wire transfer).

## Why 4 decisions, not a binary allow/block

REWRITE and REQUIRE_APPROVAL are what make this a *safety layer* rather than a *filter*. A pure allow/block system either lets unsafe actions through or makes the agent completely unable to do borderline-risky-but-legitimate work (a human approving a $50k vendor payment is normal business, not something to hard-block). REWRITE specifically demonstrates that AgentGuard can be constructive, not just restrictive — instead of only saying "no," it can produce a modified action (e.g., reroute an external recipient to an internal review queue) that accomplishes a safe version of the original intent.

## Prior art this design draws on

- **Fraud/risk rules engines + ML scoring** (common in payments/fintech): deterministic rules produce auditable signals; a model refines/prioritizes, but rarely has unchecked final authority over a hard block.
- **API gateways / policy-as-code (OPA-style)**: the idea of an explicit, inspectable policy catalog that every request is checked against, independent of the application logic making the request.
- **Content moderation systems**: multi-tier decisions (allow / flag for review / auto-remove) rather than binary allow/block, because the cost of a false positive (blocking legitimate work) and a false negative (missing real harm) are both high and asymmetric.

## What we deliberately did not build (see LIMITATIONS.md)

Real tool execution, persistent multi-tenant policy configuration, a human approval UI/workflow, fine-tuned or learned risk scoring, and multi-turn/session-aware evaluation were all explicitly scoped out to keep the 24-hour build focused on a working, explainable, end-to-end interception pipeline.
