"""Node 3: Financial Analysis.

Calls all deterministic financial analysis tools.
No LLM involvement here — pure Python/Pandas calculations.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.agent.state import FinancialInvestigationState, WorkflowStep
from app.services.financial_engine import (
    get_period_metrics,
    compare_periods,
    analyze_categories,
    compare_categories,
    analyze_products,
    compare_products,
    analyze_suppliers,
    compare_suppliers,
)

logger = logging.getLogger(__name__)


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


def _metrics_to_dict(metrics) -> dict:
    return asdict(metrics)


def financial_analysis_node(
    state: FinancialInvestigationState,
    db: Session,
) -> FinancialInvestigationState:
    """
    LangGraph node: Financial Analysis.
    Computes metrics and period comparisons using deterministic tools.
    """
    _trace_step(state, f"Calculating metrics for {state['current_period']}", "running")

    current_period = state["current_period"]
    comparison_period = state["comparison_period"]
    tools = state.get("tools_to_run", [])

    try:
        # Always compute period metrics
        cur_metrics = get_period_metrics(db, current_period)
        cmp_metrics = get_period_metrics(db, comparison_period)

        state["current_metrics"] = _metrics_to_dict(cur_metrics)
        state["comparison_metrics"] = _metrics_to_dict(cmp_metrics)

        _trace_step(state, f"Calculating metrics for {state['current_period']}", "completed",
                    f"Revenue: ${cur_metrics.revenue:,.0f} | Profit: ${cur_metrics.net_profit:,.0f}")

        # Period comparison
        if "compare_periods" in tools:
            _trace_step(state, f"Comparing {current_period} with {comparison_period}", "running")
            comps = compare_periods(db, current_period, comparison_period)
            state["comparison_results"] = {
                k: {
                    "metric": v.metric,
                    "current_value": v.current_value,
                    "comparison_value": v.comparison_value,
                    "change": v.change,
                    "change_pct": v.change_pct,
                    "direction": v.direction,
                }
                for k, v in comps.items()
            }
            profit_change = comps.get("net_profit")
            _trace_step(state, f"Comparing {current_period} with {comparison_period}", "completed",
                        f"Profit change: ${profit_change.change:,.0f}" if profit_change else "")

        # Category analysis
        if "analyze_categories" in tools:
            _trace_step(state, "Analyzing category performance", "running")
            cat_comps = compare_categories(db, current_period, comparison_period)
            state["category_analysis"] = cat_comps
            _trace_step(state, "Analyzing category performance", "completed",
                        f"{len(cat_comps)} categories analyzed")

        # Product analysis
        if "analyze_products" in tools:
            _trace_step(state, "Analyzing product margins", "running")
            prod_comps = compare_products(db, current_period, comparison_period)
            state["product_analysis"] = prod_comps
            _trace_step(state, "Analyzing product margins", "completed",
                        f"{len(prod_comps)} products analyzed")

        # Supplier analysis
        if "analyze_suppliers" in tools:
            _trace_step(state, "Analyzing supplier costs", "running")
            sup_comps = compare_suppliers(db, current_period, comparison_period)
            state["supplier_analysis"] = sup_comps
            _trace_step(state, "Analyzing supplier costs", "completed",
                        f"{len(sup_comps)} suppliers analyzed")

    except Exception as exc:
        logger.exception("[%s] Financial analysis failed", state["investigation_id"])
        state["errors"].append(f"Financial analysis error: {exc}")
        _trace_step(state, "Financial analysis", "failed", str(exc))

    return state
