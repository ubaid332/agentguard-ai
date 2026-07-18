"""AgentGuard: the interceptor that orchestrates the full pipeline.

This is the single entry point the API (and any future integration) calls.
It wires together the pieces from the architecture diagram in order:
TaskAgent -> ComplianceReasoner -> audit log. Nothing here talks to the
Anthropic SDK directly - that's encapsulated in agent.py/reasoner.py/
llm_client.py, keeping this module a pure orchestrator.
"""

from __future__ import annotations

from app import db
from app.agent import TaskAgent
from app.reasoner import ComplianceReasoner
from app.schemas import EvaluationResult


class AgentGuard:
    def __init__(self) -> None:
        self.agent = TaskAgent()
        self.reasoner = ComplianceReasoner()

    async def process_task(self, task: str) -> EvaluationResult:
        proposed_action = await self.agent.propose_action(task)
        result = await self.reasoner.evaluate(task, proposed_action)
        result.id = db.log_evaluation(result)
        return result


# Module-level singleton - the agent/reasoner hold no per-request state, so
# one instance is safe to share across requests.
agent_guard = AgentGuard()
