"""FastAPI application: the HTTP surface AgentGuard exposes.

Routes are intentionally thin - all real work happens in guard.py /
reasoner.py / policies.py. This module's only job is request/response
plumbing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.guard import agent_guard
from app.llm_client import is_available
from app.schemas import DemoScenario, EvaluateRequest, EvaluationResult
from app.scenarios import DEMO_SCENARIOS


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="AgentGuard AI",
    description="Runtime safety and compliance layer for AI agent tool actions.",
    version="0.1.0",
    lifespan=lifespan,
)

# Local hackathon demo: Streamlit runs on a different port, so open CORS wide.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "llm_enabled": is_available()}


@app.get("/api/scenarios", response_model=list[DemoScenario])
async def list_scenarios() -> list[DemoScenario]:
    return DEMO_SCENARIOS


@app.post("/api/evaluate", response_model=EvaluationResult)
async def evaluate(request: EvaluateRequest) -> EvaluationResult:
    try:
        return await agent_guard.process_task(request.task)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/history", response_model=list[EvaluationResult])
async def history(limit: int = 50) -> list[EvaluationResult]:
    return db.get_history(limit=limit)
