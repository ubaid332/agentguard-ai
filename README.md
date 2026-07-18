# AgentGuard AI

**A runtime safety and compliance layer for AI agents.**

AgentGuard intercepts an AI agent's proposed tool action *before* it executes, evaluates it against a policy engine and an LLM-based compliance reasoner, assigns a risk score, and returns one of four decisions — **ALLOW**, **BLOCK**, **REWRITE**, or **REQUIRE_APPROVAL** — with a plain-language explanation. Every evaluation is logged for audit.

Built for the Hack-Nation Global AI Hackathon.

---

## The Problem

AI agents are increasingly given real tools: sending emails, transferring funds, deleting database records, posting to Slack, modifying access permissions. Today, whether a given agent action is safe to execute is left almost entirely to the underlying model's judgment and whatever ad-hoc guardrails a developer bolted on. There is no standard runtime layer that:

- Intercepts a proposed action *before* it runs (not after, via logs)
- Evaluates it against explicit, auditable policies
- Produces a structured, explainable risk verdict
- Can automatically rewrite an unsafe action into a safe one instead of just blocking it
- Logs every decision for compliance review

As agents get more autonomy, this gap becomes the difference between "the agent emailed a customer" and "the agent emailed a customer's SSN to an external address."

## The Solution

AgentGuard sits between an AI agent's decision-making and tool execution, as a dedicated interceptor:

```
User task ("send the invoice to billing@client.com")
        │
        ▼
   AI Agent (LLM)  ──►  Proposed Action (structured: tool, params, data sensitivity)
        │
        ▼
 AgentGuard Interceptor
        │
        ▼
   Policy Engine (deterministic) ──► detected risks, violated policies, base risk score
        │
        ▼
 Compliance Reasoner (LLM)  ──► explanation, refined risk score, safe rewrite (if possible)
        │
        ▼
   Decision thresholds (code) ──► ALLOW / BLOCK / REWRITE / REQUIRE_APPROVAL
        │
        ├──► Audit Log (SQLite)
        └──► Dashboard (Streamlit)
```

The key design decision: **the LLM never decides the final verdict.** A deterministic policy engine computes risk signals and a base score from explicit rules (sensitive data, external recipients, secrets, destructive database operations, large financial transactions, production changes, public channel exposure); an LLM compliance reasoner explains those signals in plain language, spots anything the rules missed, and can draft a safe rewritten version of the action. The actual ALLOW/BLOCK/REWRITE/REQUIRE_APPROVAL decision is computed from the final risk score by fixed thresholds in code. This makes outcomes reproducible and means AgentGuard **degrades gracefully to a fully rule-based system if the LLM is unavailable** — it never crashes or hangs the pipeline waiting on an API call.

## Architecture

```
agentguard-ai/
  app/
    schemas.py     # Pydantic models shared across every layer
    policies.py    # Deterministic PolicyEngine + 7 demo policies
    config.py      # Settings (API key, model, DB path) from env/.env
    llm_client.py  # Async Anthropic client wrapper, offline-safe
    agent.py       # TaskAgent: NL task -> structured ProposedAction
    reasoner.py    # ComplianceReasoner: policies + LLM -> EvaluationResult
    db.py          # SQLite audit log
    scenarios.py   # 6 predefined demo tasks
    guard.py       # AgentGuard: orchestrates the full pipeline
    main.py        # FastAPI routes
  streamlit_app.py # Dashboard UI
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full component-by-component breakdown, [RESEARCH.md](RESEARCH.md) for the reasoning behind the policy/LLM split, and [LIMITATIONS.md](LIMITATIONS.md) for what this MVP deliberately does not handle.

## Setup

**Requirements:** Python 3.11+ (tested on 3.14), an Anthropic API key (optional — the app runs fully offline without one, using the deterministic policy engine only).

```bash
git clone <this-repo>
cd agentguard-ai
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY (optional but recommended for the full demo)
```

Run the backend and the dashboard in two terminals:

```bash
# Terminal 1 — API
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Dashboard
streamlit run streamlit_app.py
```

Open the dashboard at **http://localhost:8501**. The FastAPI docs (Swagger UI) are at **http://localhost:8000/docs**.

## Demo Scenarios

The dashboard sidebar has one-click buttons for six predefined tasks, chosen to span all four decisions:

| Scenario | Task | Expected Decision |
|---|---|---|
| Routine welcome email | Send a welcome email to a new user's company address | **ALLOW** |
| Financial data leak | Email a customer's financial statement + SSN to an external Gmail address | **BLOCK** |
| External report | Send a sales report to an external partner (no PII) | **REWRITE** (rerouted internally) |
| Production DB cleanup | Delete old log entries from the production database | **REQUIRE_APPROVAL** |
| Secret exposure | Post API keys and a DB password to a public Slack channel | **BLOCK** |
| Large transfer | Transfer $50,000 to a vendor account | **REQUIRE_APPROVAL** |

You can also type any free-text task into the input box — the same pipeline runs regardless of whether the task came from a demo button or a custom description; the user never manually enters an "AI response" or picks a policy.

## Future Potential

- **Real tool execution hook**: gate an actual `send_email`/`transfer_funds`/etc. call behind the decision instead of only simulating it.
- **Configurable policy packs**: per-organization policy sets (finance, healthcare/HIPAA, general SaaS) loaded at runtime instead of hardcoded.
- **Human-in-the-loop approval queue**: a real approval workflow for REQUIRE_APPROVAL decisions instead of just logging them.
- **Streaming/webhook integration**: plug into existing agent frameworks (LangChain, Claude Agent SDK, Managed Agents) as a tool-call middleware.
- **Fine-tuned risk scoring**: replace fixed policy weights with a learned model calibrated against real incident data.
- **Multi-turn context**: evaluate an action in light of the agent's prior actions in the same session, not just in isolation.
