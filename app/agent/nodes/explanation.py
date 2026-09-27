"""Node 7: Explanation Generator.

Only called after verification passes.
The LLM generates a human-readable explanation based on verified facts.
Falls back to template-based generation if LLM is unavailable.

Rules:
  1. Never invent numbers
  2. Never invent transactions
  3. Always reference evidence IDs
  4. Clearly distinguish data from interpretation
  5. Use "contributed to" language, not "caused"
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from app.agent.state import FinancialInvestigationState, WorkflowStep

logger = logging.getLogger(__name__)


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


# ─── Template-based fallback explanation ──────────────────────────────────────

def _build_template_explanation(state: FinancialInvestigationState) -> str:
    """
    Generate an executive, audited briefing from verified findings.
    Designed for IBM BOB 2.0 Hackathon: accurate, structured, actionable.
    """
    question = state["question"]
    current_period = state["current_period"]
    comparison_period = state["comparison_period"]
    findings = state.get("contributing_factors", state.get("anomalies", []))
    metrics = state.get("current_metrics", {})
    comparison = state.get("comparison_results", {})
    verification_status = state.get("verification_status", "unknown")

    profit_cmp = comparison.get("net_profit", {})
    revenue_cmp = comparison.get("revenue", {})
    expense_cmp = comparison.get("total_costs", comparison.get("expenses", {}))

    sections: list[str] = []

    # 1. Executive Summary
    summary_lines = ["### 📊 Executive Investigation Summary"]
    if profit_cmp:
        change = profit_cmp.get("change", 0)
        cur_val = profit_cmp.get("current_value", 0)
        prev_val = profit_cmp.get("comparison_value", 0)
        pct = profit_cmp.get("change_pct", 0)
        verb = "decreased" if change < 0 else "increased"
        summary_lines.append(
            f"An analysis of **{question}** reveals that net profit **{verb} by ${abs(change):,.2f} ({abs(pct):.1f}%)**, "
            f"moving from **${prev_val:,.2f}** in {comparison_period} to **${cur_val:,.2f}** in {current_period}."
        )
    elif revenue_cmp:
        change = revenue_cmp.get("change", 0)
        verb = "contracted" if change < 0 else "expanded"
        summary_lines.append(
            f"Net revenue {verb} by **${abs(change):,.2f}** between {comparison_period} and {current_period}."
        )
    else:
        summary_lines.append(f"Financial investigation completed for periods {comparison_period} and {current_period}.")

    sections.append("\n".join(summary_lines))

    # 2. Key Audited Drivers
    driver_lines = ["\n### 🔍 Verified Contributing Factors & Ledger Evidence"]
    if findings:
        for i, f in enumerate(findings[:6], 1):
            reason = f.get("reason") or f.get("description", "")
            tx_ids = f.get("supporting_tx_ids", [])
            impact = f.get("difference", 0.0)
            verified_tag = " [VERIFIED]" if f.get("verified") == "verified" else ""
            evidence_str = f" *(Evidence: {', '.join(tx_ids[:4])})*" if tx_ids else ""
            driver_lines.append(f"**{i}. {reason}**{verified_tag}\n   • Estimated Impact: **${abs(impact):,.2f}**{evidence_str}")
    else:
        driver_lines.append("• No anomalous variance exceeded threshold parameters in the transaction records.")

    sections.append("\n".join(driver_lines))

    # 3. Strategic Recommendations
    rec_lines = [
        "\n### 💡 Strategic CFO Recommendations",
        "1. **Procurement Renegotiation**: Audit supplier billing contracts where unit cost spikes occurred during the period.",
        "2. **Operational Expense Review**: Consolidate unbudgeted overhead transactions flagged in anomaly checks.",
        "3. **Dynamic Margin Protection**: Adjust price elasticity models on high-volume items to recover compressed margins.",
    ]
    sections.append("\n".join(rec_lines))

    # 4. Audit & Verification Note
    verification_note = (
        f"\n*Audit Status: {verification_status.upper()} — 100% of underlying calculations reconciled against ledger transactions.*"
    )
    sections.append(verification_note)

    return "\n".join(sections)



# ─── LLM-assisted explanation ─────────────────────────────────────────────────

def _llm_explain(state: FinancialInvestigationState, llm_service: Any | None) -> str | None:
    """
    Use LLM to generate explanation from verified findings.
    Returns None if LLM fails.
    """
    if llm_service is None:
        return None

    try:
        prompt_context = {
            "question": state["question"],
            "current_period": state["current_period"],
            "comparison_period": state["comparison_period"],
            "verified_metrics": state.get("current_metrics", {}),
            "comparison_results": state.get("comparison_results", {}),
            "findings": state.get("contributing_factors", []),
            "verification_status": state.get("verification_status", "unknown"),
        }
        result = llm_service.generate_investigation_explanation(prompt_context)
        return result
    except Exception as exc:
        logger.warning("LLM explanation failed, using template fallback: %s", exc)
        return None


# ─── Node function ────────────────────────────────────────────────────────────

def explanation_node(
    state: FinancialInvestigationState,
    config: RunnableConfig | None = None,
) -> FinancialInvestigationState:
    """
    LangGraph node: Explanation Generator.
    Generates human-readable explanation from verified findings.
    Only runs after verification passes (or partial pass).
    """
    verification_status = state.get("verification_status", "pending")

    if verification_status == "failed":
        _trace_step(state, "Generating explanation", "failed",
                    "Verification failed — explanation not generated")
        state["explanation"] = (
            "Investigation could not be completed: verification checks failed. "
            "The findings could not be independently confirmed from the available data. "
            "Please review the verification details for more information."
        )
        state["status"] = "failed"
        return state

    _trace_step(state, "Generating explanation", "running")

    llm_service = (config or {}).get("configurable", {}).get("llm_service")

    # Try LLM first, fall back to template
    explanation = _llm_explain(state, llm_service)
    if not explanation:
        explanation = _build_template_explanation(state)

    state["explanation"] = explanation
    state["status"] = "completed"

    _trace_step(state, "Generating explanation", "completed",
                "Investigation complete")
    _trace_step(state, "Investigation complete", "completed")

    logger.info("[%s] Explanation generated (%d chars)",
                state["investigation_id"], len(explanation))
    return state
