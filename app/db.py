"""SQLite audit log.

Every evaluation AgentGuard performs is written here, regardless of the
decision, so the system has a full compliance trail. Uses stdlib sqlite3
directly (no ORM) to keep the hackathon footprint small.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.config import settings
from app.schemas import Decision, EvaluationResult, ProposedAction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    task TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    decision TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    detected_risks TEXT NOT NULL,
    violated_policies TEXT NOT NULL,
    explanation TEXT NOT NULL,
    safe_rewritten_action TEXT,
    reasoning_source TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.agentguard_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_SCHEMA)


def log_evaluation(result: EvaluationResult) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_log
                (timestamp, task, proposed_action, decision, risk_score,
                 detected_risks, violated_policies, explanation,
                 safe_rewritten_action, reasoning_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.timestamp.isoformat(),
                result.task,
                result.proposed_action.model_dump_json(),
                result.decision.value,
                result.risk_score,
                json.dumps(result.detected_risks),
                json.dumps(result.violated_policies),
                result.explanation,
                result.safe_rewritten_action.model_dump_json() if result.safe_rewritten_action else None,
                result.reasoning_source,
            ),
        )
        return cursor.lastrowid


def _row_to_result(row: sqlite3.Row) -> EvaluationResult:
    return EvaluationResult(
        id=row["id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        task=row["task"],
        proposed_action=ProposedAction.model_validate_json(row["proposed_action"]),
        decision=Decision(row["decision"]),
        risk_score=row["risk_score"],
        detected_risks=json.loads(row["detected_risks"]),
        violated_policies=json.loads(row["violated_policies"]),
        explanation=row["explanation"],
        safe_rewritten_action=(
            ProposedAction.model_validate_json(row["safe_rewritten_action"])
            if row["safe_rewritten_action"]
            else None
        ),
        reasoning_source=row["reasoning_source"],
    )


def get_history(limit: int = 50) -> list[EvaluationResult]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_result(row) for row in rows]
