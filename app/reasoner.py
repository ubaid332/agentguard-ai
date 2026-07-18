"""ComplianceReasoner: the core of AgentGuard's decision-making.

Design: the PolicyEngine (deterministic, no LLM) always runs first and
produces the ground-truth risk signals. The LLM is then asked to explain
those signals in plain language and, where the risk is remediable, draft a
safe rewritten action — but it does NOT get to invent the final decision.
The risk score is a bounded blend of the policy engine's score and the LLM's
own read of severity, and the ALLOW/BLOCK/REWRITE/REQUIRE_APPROVAL decision
is computed from that score by fixed thresholds in code. This keeps outcomes
reproducible for the demo and means the system still works (with a slightly
more mechanical explanation) if the LLM is unavailable.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.llm_client import structured_call
from app.policies import POLICIES, PolicyEngine
from app.schemas import Decision, EvaluationResult, ProposedAction

# --- decision thresholds -----------------------------------------------
# Tuned against the worked example in the spec (external recipient + high-
# sensitivity financial data -> policy engine alone already scores 75) and
# the six demo scenarios so that each maps to its intended decision even
# with the LLM offline.
BLOCK_THRESHOLD = 75
REQUIRE_APPROVAL_THRESHOLD = 50
REWRITE_THRESHOLD = 25


def _decide(risk_score: int, has_rewrite: bool) -> Decision:
    if risk_score >= BLOCK_THRESHOLD:
        return Decision.BLOCK
    if risk_score >= REQUIRE_APPROVAL_THRESHOLD:
        return Decision.REQUIRE_APPROVAL
    if risk_score >= REWRITE_THRESHOLD and has_rewrite:
        return Decision.REWRITE
    if risk_score >= REWRITE_THRESHOLD:
        return Decision.REQUIRE_APPROVAL
    return Decision.ALLOW


class _LLMAssessment(BaseModel):
    """What we ask the LLM to contribute — explanation and severity only,
    never the decision itself."""

    explanation: str = Field(description="2-3 sentences explaining the risk in plain language for a compliance dashboard")
    additional_risks: list[str] = Field(
        default_factory=list, description="Any risks the policy engine's detected_risks list missed, if any"
    )
    severity_adjustment: int = Field(
        default=0,
        ge=-15,
        le=15,
        description="Fine adjustment to the deterministic risk score, from -15 (policy engine overestimated) to +15 (underestimated)",
    )
    can_be_made_safe: bool = Field(
        description="True if a modified version of the action would resolve the risk (e.g. redact a field, change recipient, remove secrets)"
    )
    safe_rewritten_action: ProposedAction | None = Field(
        default=None, description="A safer version of the action, only if can_be_made_safe is true"
    )


REASONER_SYSTEM_PROMPT = f"""You are the compliance reasoning layer of AgentGuard, a runtime
safety system that reviews AI agent tool calls before they execute. You are
given a proposed action and a list of policies a deterministic rule engine
already flagged, with a base risk score out of 100.

Your job is NOT to decide ALLOW/BLOCK/REWRITE/REQUIRE_APPROVAL (a separate
component computes that from the risk score). Your job is to:
1. Write a clear, specific 2-3 sentence explanation of the risk for a human
   reviewer, referencing the actual data/recipients/amounts involved.
2. Note any additional risks the rule engine's keyword matching may have
   missed.
3. Suggest a small adjustment (-15 to +15) to the risk score if the rule
   engine's flat keyword-weight scoring over- or under-states the real
   severity given the full context.
4. If the risk is remediable (e.g. an external recipient could be swapped
   for an internal one, sensitive fields could be redacted, a secret could
   be removed), propose a safe_rewritten_action with the same tool_name and
   the fix applied. If the action is fundamentally unsafe and no small edit
   fixes it (e.g. leaking credentials, a destructive database wipe), set
   can_be_made_safe to false and leave safe_rewritten_action null.

Policy catalog for reference:
{chr(10).join(f"- {p.id} {p.name}: {p.description}" for p in POLICIES)}
"""


class ComplianceReasoner:
    def __init__(self, policy_engine: PolicyEngine | None = None):
        self.policy_engine = policy_engine or PolicyEngine()

    async def evaluate(self, task: str, action: ProposedAction) -> EvaluationResult:
        pe_result = self.policy_engine.evaluate(action)

        assessment = await self._get_llm_assessment(action, pe_result)

        if assessment is not None:
            risk_score = max(0, min(100, pe_result.base_risk_score + assessment.severity_adjustment))
            detected_risks = list(pe_result.detected_risks) + [
                r for r in assessment.additional_risks if r not in pe_result.detected_risks
            ]
            explanation = assessment.explanation
            safe_rewrite = assessment.safe_rewritten_action if assessment.can_be_made_safe else None
            source = "llm+policy_engine"
        else:
            risk_score = pe_result.base_risk_score
            detected_risks = pe_result.detected_risks
            explanation = self._fallback_explanation(pe_result, action)
            safe_rewrite = self._fallback_rewrite(action, pe_result)
            source = "policy_engine"

        decision = _decide(risk_score, has_rewrite=safe_rewrite is not None)
        # A rewrite is only useful if we actually produced one; if the
        # decision landed on REWRITE but we have none, fall back to approval.
        if decision == Decision.REWRITE and safe_rewrite is None:
            decision = Decision.REQUIRE_APPROVAL

        return EvaluationResult(
            task=task,
            proposed_action=action,
            decision=decision,
            risk_score=risk_score,
            detected_risks=detected_risks or ["No specific risks detected."],
            violated_policies=pe_result.violated_policies,
            explanation=explanation,
            safe_rewritten_action=safe_rewrite,
            reasoning_source=source,
        )

    async def _get_llm_assessment(self, action: ProposedAction, pe_result) -> _LLMAssessment | None:
        user_prompt = (
            f"Proposed action:\n{action.model_dump_json(indent=2)}\n\n"
            f"Rule-engine detected risks: {json.dumps(pe_result.detected_risks)}\n"
            f"Rule-engine violated policies: {json.dumps(pe_result.violated_policies)}\n"
            f"Rule-engine base risk score: {pe_result.base_risk_score}/100"
        )
        return await structured_call(
            system=REASONER_SYSTEM_PROMPT,
            user=user_prompt,
            output_model=_LLMAssessment,
            max_tokens=1536,
        )

    @staticmethod
    def _fallback_explanation(pe_result, action: ProposedAction) -> str:
        if not pe_result.violated_policies:
            return (
                f"No policy violations detected for '{action.action}'. "
                "This action appears safe to execute automatically."
            )
        policies = "; ".join(pe_result.violated_policies)
        return (
            f"This action ('{action.action}' via {action.tool_name}) triggered {len(pe_result.violated_policies)} "
            f"polic{'y' if len(pe_result.violated_policies) == 1 else 'ies'}: {policies}. "
            f"Base rule-engine risk score: {pe_result.base_risk_score}/100. "
            "(Generated via offline deterministic fallback - no LLM available.)"
        )

    @staticmethod
    def _fallback_rewrite(action: ProposedAction, pe_result) -> ProposedAction | None:
        """Very small set of mechanical rewrites for the offline fallback path."""
        violated_ids = {p.split(":")[0] for p in pe_result.violated_policies}
        if "POL-003" in violated_ids or "POL-004" in violated_ids:
            # secrets or destructive DB ops are never auto-rewritable
            return None
        if "POL-002" in violated_ids and "POL-001" not in violated_ids:
            # external recipient only, no sensitive data — safe to reroute internally
            new_params = dict(action.parameters)
            for key, value in new_params.items():
                if "@" in value:
                    new_params[key] = "compliance-review@company.com"
            return ProposedAction(
                tool_name=action.tool_name,
                action=f"{action.action} (rerouted to internal review)",
                parameters=new_params,
                data_sensitivity=action.data_sensitivity,
                reasoning="Recipient rerouted to an approved internal domain pending review.",
            )
        return None
