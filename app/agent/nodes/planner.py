"""Node 2: Investigation Planner.

Creates a deterministic investigation plan based on the detected intent.
The plan specifies which analysis tools to run.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from app.agent.state import FinancialInvestigationState, WorkflowStep

logger = logging.getLogger(__name__)

# ─── Tool Definitions ─────────────────────────────────────────────────────────

ALL_TOOLS = {
    "calculate_period_metrics": "Calculate revenue, expenses, COGS, and profit for both periods",
    "compare_periods": "Compute period-over-period changes for all key metrics",
    "analyze_categories": "Analyze revenue and margin by product category",
    "analyze_products": "Analyze gross margin per product",
    "analyze_suppliers": "Analyze cost per supplier",
    "detect_anomalies": "Detect significant changes and anomalies",
    "retrieve_evidence": "Retrieve supporting transactions for each finding",
    "verify_findings": "Independently verify all calculations before explanation",
}

# ─── Intent → Tools mapping ───────────────────────────────────────────────────

INTENT_PLANS: dict[str, dict[str, Any]] = {
    "profit_change_investigation": {
        "steps": [
            "Compare {current_period} with {comparison_period}",
            "Calculate revenue change",
            "Calculate expense change",
            "Calculate COGS change",
            "Calculate refund impact",
            "Analyze category performance",
            "Analyze product margins",
            "Analyze supplier costs",
            "Detect anomalies and contributing factors",
            "Retrieve supporting evidence",
            "Verify all findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "compare_periods",
            "analyze_categories",
            "analyze_products",
            "analyze_suppliers",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "revenue_change_investigation": {
        "steps": [
            "Compare revenue in {current_period} with {comparison_period}",
            "Analyze revenue by category",
            "Analyze revenue by product",
            "Detect revenue anomalies",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "compare_periods",
            "analyze_categories",
            "analyze_products",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "expense_change_investigation": {
        "steps": [
            "Compare expenses in {current_period} with {comparison_period}",
            "Analyze expense categories",
            "Analyze supplier costs",
            "Detect expense anomalies",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "compare_periods",
            "analyze_suppliers",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "margin_change_investigation": {
        "steps": [
            "Compare gross margins in {current_period} with {comparison_period}",
            "Analyze category margins",
            "Analyze product margins",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "compare_periods",
            "analyze_categories",
            "analyze_products",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "refund_change_investigation": {
        "steps": [
            "Compare refunds in {current_period} with {comparison_period}",
            "Analyze refunds by category",
            "Analyze refunds by product",
            "Detect refund anomalies",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "compare_periods",
            "analyze_categories",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "supplier_analysis_investigation": {
        "steps": [
            "Analyze supplier costs in {current_period}",
            "Compare supplier costs with {comparison_period}",
            "Detect supplier cost anomalies",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "analyze_suppliers",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "product_performance_investigation": {
        "steps": [
            "Analyze product performance in {current_period}",
            "Compare products with {comparison_period}",
            "Detect product margin changes",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "analyze_products",
            "analyze_categories",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "anomaly_detection_investigation": {
        "steps": [
            "Scan for unusual transactions in {current_period}",
            "Compare with baseline {comparison_period}",
            "Detect transaction anomalies",
            "Check for duplicate transactions",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
    "general_financial_investigation": {
        "steps": [
            "Compare {current_period} with {comparison_period}",
            "Calculate all key metrics",
            "Analyze categories, products, and suppliers",
            "Detect anomalies",
            "Retrieve supporting evidence",
            "Verify findings",
            "Generate explanation",
        ],
        "tools": [
            "calculate_period_metrics",
            "compare_periods",
            "analyze_categories",
            "analyze_products",
            "analyze_suppliers",
            "detect_anomalies",
            "retrieve_evidence",
            "verify_findings",
        ],
    },
}


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


# ─── Node function ────────────────────────────────────────────────────────────

def investigation_planner_node(
    state: FinancialInvestigationState,
    config: RunnableConfig | None = None,
) -> FinancialInvestigationState:
    """
    LangGraph node: Investigation Planner.
    Selects the appropriate investigation plan and tool set based on intent.
    """
    _trace_step(state, "Creating investigation plan", "running")

    intent = state.get("intent") or "general_financial_investigation"
    current_period = state["current_period"]
    comparison_period = state["comparison_period"]

    plan_template = INTENT_PLANS.get(intent, INTENT_PLANS["general_financial_investigation"])

    # Render step descriptions with actual periods
    rendered_steps = [
        step.format(current_period=current_period, comparison_period=comparison_period)
        for step in plan_template["steps"]
    ]

    state["investigation_plan"] = rendered_steps
    state["tools_to_run"] = plan_template["tools"]

    _trace_step(state, "Creating investigation plan", "completed",
                f"Plan: {len(rendered_steps)} steps | Tools: {len(plan_template['tools'])}")

    logger.info("[%s] Plan created: %d steps, tools: %s",
                state["investigation_id"], len(rendered_steps), plan_template["tools"])
    return state
