"""Shared Pydantic data contracts for AgentGuard.

These models are the single source of truth for the shape of data passed
between the TaskAgent, PolicyEngine, ComplianceReasoner, FastAPI routes,
SQLite audit log, and the Streamlit UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DataSensitivity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REWRITE = "REWRITE"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class ProposedAction(BaseModel):
    """A structured tool call an AI agent wants to execute, before it runs."""

    tool_name: str = Field(description="Name of the tool being invoked, e.g. 'send_email'")
    action: str = Field(description="Short verb phrase describing the action, e.g. 'send external email'")
    parameters: dict[str, str] = Field(
        default_factory=dict,
        description="Tool call parameters as key-value pairs, e.g. {'recipient': '...', 'body': '...'}",
    )
    data_sensitivity: DataSensitivity = Field(
        default=DataSensitivity.NONE,
        description="Sensitivity of the data touched by this action, inferred from the task",
    )
    reasoning: str = Field(
        default="",
        description="One sentence on why the agent chose this tool call for the task",
    )


class EvaluationResult(BaseModel):
    """The full AgentGuard verdict for one proposed action."""

    id: Optional[int] = None
    task: str
    proposed_action: ProposedAction
    decision: Decision
    risk_score: int = Field(ge=0, le=100)
    detected_risks: list[str] = Field(default_factory=list)
    violated_policies: list[str] = Field(default_factory=list)
    explanation: str
    safe_rewritten_action: Optional[ProposedAction] = None
    reasoning_source: str = Field(
        default="policy_engine",
        description="'policy_engine' (deterministic only) or 'llm+policy_engine' (LLM-refined)",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvaluateRequest(BaseModel):
    task: str = Field(min_length=1, description="Natural-language task the user wants the agent to perform")


class DemoScenario(BaseModel):
    id: str
    title: str
    task: str
    expected_decision: Decision
