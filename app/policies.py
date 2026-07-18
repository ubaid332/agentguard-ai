"""Deterministic policy engine.

This is the "ground truth" safety layer: a fixed set of demo policies, each
with simple keyword/regex detectors and a risk weight. It runs with no LLM
call and no network access, so AgentGuard can always produce a sensible,
reproducible verdict even if the LLM is unavailable — and it gives the LLM
reasoner a set of pre-computed signals to explain rather than invent from
scratch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app.schemas import DataSensitivity, ProposedAction

# Domains treated as "internal" / approved for this demo org. Anything else
# in a recipient-like field counts as an external transfer.
APPROVED_DOMAINS = {"company.com", "ourcompany.com", "agentguard.ai"}

EXTERNAL_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")

SENSITIVE_KEYWORDS = [
    "financial statement", "ssn", "social security", "credit card", "bank account",
    "salary", "medical record", "health record", "passport", "customer data",
    "customer financial", "financial information",
]

SECRET_KEYWORDS = [
    "api key", "api_key", "password", "secret key", "access token", "private key",
    ".env", "credential",
]

DESTRUCTIVE_VERBS = ["delete", "drop", "truncate", "purge", "wipe"]

PRODUCTION_KEYWORDS = ["production", "prod ", "prod-", "prod_", "live database"]

LARGE_AMOUNT_RE = re.compile(r"\$?\s?(\d[\d,]{3,})")  # 4+ digit amounts, e.g. $50,000


@dataclass
class Policy:
    id: str
    name: str
    category: str
    description: str
    weight: int  # risk points contributed if triggered
    detector: Callable[[ProposedAction, str], bool]  # (action, flattened_text) -> triggered?

    def check(self, action: ProposedAction, flat_text: str) -> bool:
        return self.detector(action, flat_text)


def _flatten(action: ProposedAction) -> str:
    parts = [action.tool_name, action.action, action.reasoning]
    parts.extend(f"{k}: {v}" for k, v in action.parameters.items())
    return " | ".join(parts).lower()


def _external_recipient(action: ProposedAction, flat_text: str) -> bool:
    for value in action.parameters.values():
        for match in EXTERNAL_EMAIL_RE.finditer(value):
            domain = match.group(1).lower()
            if domain not in APPROVED_DOMAINS:
                return True
    return False


def _sensitive_data(action: ProposedAction, flat_text: str) -> bool:
    if action.data_sensitivity in (DataSensitivity.HIGH, DataSensitivity.MEDIUM):
        return True
    return any(kw in flat_text for kw in SENSITIVE_KEYWORDS)


def _secret_exposure(action: ProposedAction, flat_text: str) -> bool:
    return any(kw in flat_text for kw in SECRET_KEYWORDS)


def _destructive_db_operation(action: ProposedAction, flat_text: str) -> bool:
    tool = action.tool_name.lower()
    if "database" not in tool and "db" not in tool and "record" not in tool:
        # still allow verb-based detection against the flattened text
        pass
    return any(v in flat_text for v in DESTRUCTIVE_VERBS) and (
        "database" in flat_text or "record" in flat_text or "table" in flat_text
    )


def _production_change(action: ProposedAction, flat_text: str) -> bool:
    return any(kw in flat_text for kw in PRODUCTION_KEYWORDS)


def _large_financial_transaction(action: ProposedAction, flat_text: str) -> bool:
    if "transfer" not in flat_text and "payment" not in flat_text and "pay " not in flat_text:
        return False
    for match in LARGE_AMOUNT_RE.finditer(flat_text.replace(",", "")):
        try:
            if int(match.group(1)) >= 1000:
                return True
        except ValueError:
            continue
    return False


def _public_channel_exposure(action: ProposedAction, flat_text: str) -> bool:
    return "public" in flat_text and ("slack" in flat_text or "channel" in flat_text or "post" in flat_text)


POLICIES: list[Policy] = [
    Policy(
        id="POL-001",
        name="Sensitive Data Exposure",
        category="data_protection",
        description="Action touches financial, medical, or other high-sensitivity customer data.",
        weight=40,
        detector=_sensitive_data,
    ),
    Policy(
        id="POL-002",
        name="External Data Transfer",
        category="data_exfiltration",
        description="Action sends data to a recipient outside approved company domains.",
        weight=35,
        detector=_external_recipient,
    ),
    Policy(
        id="POL-003",
        name="Credential / Secret Exposure",
        category="security",
        description="Action would expose API keys, passwords, or other secrets.",
        weight=55,
        detector=_secret_exposure,
    ),
    Policy(
        id="POL-004",
        name="Destructive Database Operation",
        category="data_integrity",
        description="Action deletes, drops, or purges database records.",
        weight=45,
        detector=_destructive_db_operation,
    ),
    Policy(
        id="POL-005",
        name="Production Environment Change",
        category="operational_risk",
        description="Action modifies a production system or live database.",
        weight=25,
        detector=_production_change,
    ),
    Policy(
        id="POL-006",
        name="Large Financial Transaction",
        category="financial_risk",
        description="Action transfers or pays out a large monetary amount ($1,000+).",
        weight=35,
        detector=_large_financial_transaction,
    ),
    Policy(
        id="POL-007",
        name="Public Channel Exposure",
        category="data_exfiltration",
        description="Action posts content to a public / unrestricted channel.",
        weight=30,
        detector=_public_channel_exposure,
    ),
]


@dataclass
class PolicyEngineResult:
    detected_risks: list[str] = field(default_factory=list)
    violated_policies: list[str] = field(default_factory=list)
    base_risk_score: int = 0


class PolicyEngine:
    """Runs every registered Policy against a ProposedAction."""

    def __init__(self, policies: list[Policy] | None = None):
        self.policies = policies or POLICIES

    def evaluate(self, action: ProposedAction) -> PolicyEngineResult:
        flat_text = _flatten(action)
        result = PolicyEngineResult()
        score = 0
        for policy in self.policies:
            if policy.check(action, flat_text):
                result.violated_policies.append(f"{policy.id}: {policy.name}")
                result.detected_risks.append(policy.description)
                score += policy.weight
        result.base_risk_score = min(score, 100)
        return result
