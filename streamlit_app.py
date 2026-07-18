"""AgentGuard AI — demo dashboard.

Talks only to the FastAPI backend over HTTP (never imports app.* directly),
mirroring the architecture diagram: User -> AI Agent -> AgentGuard
Interceptor -> ... The user only ever types a task; everything else
(tool-call generation, policy checks, LLM reasoning, decision, logging)
happens automatically behind the /api/evaluate call.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("AGENTGUARD_API_URL", "http://localhost:8000")

DECISION_STYLE = {
    "ALLOW": ("#16a34a", "✅"),
    "BLOCK": ("#dc2626", "⛔"),
    "REWRITE": ("#d97706", "✏️"),
    "REQUIRE_APPROVAL": ("#2563eb", "🔒"),
}

st.set_page_config(page_title="AgentGuard AI", page_icon="🛡️", layout="wide")


def call_api(method: str, path: str, **kwargs):
    try:
        resp = httpx.request(method, f"{API_URL}{path}", timeout=30.0, **kwargs)
        resp.raise_for_status()
        return resp.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"API error {e.response.status_code}: {e.response.text}"
    except httpx.RequestError as e:
        return None, f"Could not reach AgentGuard backend at {API_URL}: {e}"


def render_result(result: dict) -> None:
    decision = result["decision"]
    color, icon = DECISION_STYLE.get(decision, ("#6b7280", "❓"))

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown(
            f"""
            <div style="border:2px solid {color}; border-radius:10px; padding:16px; text-align:center;">
                <div style="font-size:2rem;">{icon} <b style="color:{color};">{decision.replace('_', ' ')}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.metric("Risk Score", f"{result['risk_score']} / 100")
        st.progress(result["risk_score"] / 100)

    st.caption(
        f"Reasoning source: `{result['reasoning_source']}`"
        + (" (LLM-refined)" if result["reasoning_source"] == "llm+policy_engine" else " (deterministic fallback — no LLM configured)")
    )

    st.subheader("Explanation")
    st.write(result["explanation"])

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Detected Risks")
        for r in result["detected_risks"]:
            st.markdown(f"- ⚠️ {r}")
    with c2:
        st.subheader("Violated Policies")
        if result["violated_policies"]:
            for p in result["violated_policies"]:
                st.markdown(f"- 📋 {p}")
        else:
            st.markdown("_None_")

    st.subheader("Proposed Action")
    st.json(result["proposed_action"])

    if result.get("safe_rewritten_action"):
        st.subheader("✏️ Safe Rewritten Action")
        st.caption("AgentGuard drafted a modified version of this action that resolves the flagged risk.")
        st.json(result["safe_rewritten_action"])


def main() -> None:
    st.title("🛡️ AgentGuard AI")
    st.caption("Runtime safety and compliance layer for AI agent tool actions")

    health, err = call_api("GET", "/api/health")
    if err:
        st.error(err)
        st.stop()
    if not health["llm_enabled"]:
        st.warning(
            "No Anthropic API key configured — running in deterministic offline mode. "
            "Add ANTHROPIC_API_KEY to `.env` and restart the backend for full LLM reasoning.",
            icon="⚠️",
        )

    scenarios, err = call_api("GET", "/api/scenarios")
    if err:
        st.error(err)
        st.stop()

    with st.sidebar:
        st.header("Demo Scenarios")
        st.caption("One-click predefined tasks covering all four decisions.")
        for s in scenarios:
            if st.button(f"{s['title']}", key=s["id"], use_container_width=True):
                st.session_state["task_input"] = s["task"]

        st.divider()
        st.header("Audit Log")
        history, err = call_api("GET", "/api/history", params={"limit": 20})
        if history:
            for entry in history:
                color, icon = DECISION_STYLE.get(entry["decision"], ("#6b7280", "❓"))
                st.markdown(
                    f"<span style='color:{color}'>{icon} <b>{entry['decision']}</b></span> "
                    f"(risk {entry['risk_score']}) — {entry['task'][:60]}{'...' if len(entry['task']) > 60 else ''}",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No evaluations logged yet.")

    task = st.text_area(
        "Describe the task you want the AI agent to perform:",
        key="task_input",
        placeholder="e.g. Send the customer's invoice to their billing email address",
        height=100,
    )

    if st.button("🚀 Run AgentGuard", type="primary"):
        if not task.strip():
            st.warning("Enter a task first.")
        else:
            with st.spinner("Agent proposing action → Policy engine → Compliance reasoner..."):
                result, err = call_api("POST", "/api/evaluate", json={"task": task})
            if err:
                st.error(err)
            else:
                render_result(result)


if __name__ == "__main__":
    main()
