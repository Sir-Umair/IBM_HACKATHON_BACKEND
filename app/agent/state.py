"""
LangGraph investigation state.

All fields are strongly typed.
State is predictable and serializable.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class WorkflowStep(TypedDict):
    step: str
    status: str    # "running" | "completed" | "skipped" | "failed"
    details: Optional[str]


class FindingDict(TypedDict):
    finding_type: str
    category: str
    entity: str
    metric: str
    baseline: float
    current_value: float
    difference: float
    difference_pct: float
    threshold: float
    reason: str
    supporting_tx_ids: list[str]
    severity: str
    verified: str


class VerificationCheck(TypedDict):
    check_name: str
    passed: bool
    expected: float
    actual: float
    message: str


class FinancialInvestigationState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    question: str
    current_period: str        # "YYYY-MM"
    comparison_period: str     # "YYYY-MM"
    investigation_id: str

    # ── Intent ───────────────────────────────────────────────────────────────
    intent: str                # e.g. "profit_change_investigation"
    entities: dict[str, Any]   # extracted entities (supplier names, products)

    # ── Plan ─────────────────────────────────────────────────────────────────
    investigation_plan: list[str]
    tools_to_run: list[str]

    # ── Metrics ──────────────────────────────────────────────────────────────
    current_metrics: dict[str, Any]
    comparison_metrics: dict[str, Any]
    comparison_results: dict[str, Any]   # period-over-period diffs

    # ── Analysis results ─────────────────────────────────────────────────────
    category_analysis: list[dict[str, Any]]
    product_analysis: list[dict[str, Any]]
    supplier_analysis: list[dict[str, Any]]

    # ── Findings ─────────────────────────────────────────────────────────────
    anomalies: list[FindingDict]
    contributing_factors: list[FindingDict]   # verified subset

    # ── Evidence ─────────────────────────────────────────────────────────────
    evidence: list[dict[str, Any]]            # supporting transactions

    # ── Verification ─────────────────────────────────────────────────────────
    verification_checks: list[VerificationCheck]
    verification_status: str   # "passed" | "failed" | "partial"

    # ── Output ───────────────────────────────────────────────────────────────
    explanation: str
    workflow_trace: list[WorkflowStep]

    # ── Meta ─────────────────────────────────────────────────────────────────
    errors: list[str]
    status: str   # "running" | "completed" | "failed"


def initial_state(
    question: str,
    current_period: str,
    comparison_period: str,
    investigation_id: str,
) -> FinancialInvestigationState:
    """Build a clean initial state for a new investigation."""
    return FinancialInvestigationState(
        question=question,
        current_period=current_period,
        comparison_period=comparison_period,
        investigation_id=investigation_id,
        intent="",
        entities={},
        investigation_plan=[],
        tools_to_run=[],
        current_metrics={},
        comparison_metrics={},
        comparison_results={},
        category_analysis=[],
        product_analysis=[],
        supplier_analysis=[],
        anomalies=[],
        contributing_factors=[],
        evidence=[],
        verification_checks=[],
        verification_status="pending",
        explanation="",
        workflow_trace=[],
        errors=[],
        status="running",
    )
