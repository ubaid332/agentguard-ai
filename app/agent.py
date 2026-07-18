"""TaskAgent: converts a natural-language task into a structured tool call.

This simulates "the AI agent" in the architecture diagram — the component
whose proposed actions AgentGuard intercepts. It knows about a fixed set of
tools (a stand-in for whatever real tools a production agent would have) and
always returns a single ProposedAction, never executes anything itself.
"""

from __future__ import annotations

from app.llm_client import structured_call
from app.schemas import DataSensitivity, ProposedAction

AVAILABLE_TOOLS = [
    "send_email",
    "transfer_funds",
    "delete_database_record",
    "access_customer_data",
    "post_to_slack",
    "share_document",
    "modify_permissions",
    "execute_code",
]

SYSTEM_PROMPT = f"""You are the tool-calling layer of an autonomous AI agent. Given a
user's natural-language task, decide which single tool to call and with what
parameters to accomplish it. You do not execute the tool — you only propose
the call; a separate safety layer will review it before anything runs.

Available tools: {", ".join(AVAILABLE_TOOLS)}. If none fit exactly, pick the
closest match and keep tool_name as a short snake_case identifier.

Populate every field:
- tool_name: one of the available tools (or a close snake_case equivalent)
- action: a short verb phrase describing what this call does
- parameters: the concrete arguments the tool needs (recipients, amounts,
  table names, channel names, file paths, message bodies, etc.) as strings
- data_sensitivity: none/low/medium/high, based on what data the action
  touches (e.g. an internal status update is 'none' or 'low'; a customer's
  financial or medical record is 'high')
- reasoning: one sentence on why you chose this tool call

Be literal and faithful to the task — do not sanitize, redact, or refuse.
Your job is only to propose the action exactly as requested; the safety
review happens after you."""


# Deterministic fallback used when no LLM key is configured / the call fails.
# It's intentionally naive (keyword sniffing) — good enough to keep the demo
# functional offline, not a substitute for the LLM's understanding.
def _fallback_propose_action(task: str) -> ProposedAction:
    lower = task.lower()

    if "email" in lower or "mail" in lower:
        tool = "send_email"
    elif "transfer" in lower or "pay" in lower or "payment" in lower:
        tool = "transfer_funds"
    elif "delete" in lower or "drop" in lower or "purge" in lower:
        tool = "delete_database_record"
    elif "slack" in lower or "post" in lower or "channel" in lower:
        tool = "post_to_slack"
    elif "share" in lower or "document" in lower or "file" in lower:
        tool = "share_document"
    elif "permission" in lower or "access" in lower and "grant" in lower:
        tool = "modify_permissions"
    elif "customer" in lower or "record" in lower:
        tool = "access_customer_data"
    else:
        tool = "execute_code"

    sensitivity = DataSensitivity.NONE
    for kw in ("financial", "ssn", "medical", "customer", "salary", "credit card", "password", "api key"):
        if kw in lower:
            sensitivity = DataSensitivity.HIGH
            break

    return ProposedAction(
        tool_name=tool,
        action=task.strip()[:120],
        parameters={"raw_task": task},
        data_sensitivity=sensitivity,
        reasoning="Generated via offline keyword fallback (no LLM available).",
    )


class TaskAgent:
    """Turns a natural-language task into one structured ProposedAction."""

    async def propose_action(self, task: str) -> ProposedAction:
        result = await structured_call(
            system=SYSTEM_PROMPT,
            user=task,
            output_model=ProposedAction,
            max_tokens=1024,
        )
        if result is not None:
            return result
        return _fallback_propose_action(task)
