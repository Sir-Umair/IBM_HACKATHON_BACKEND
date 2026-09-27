"""Node 4: Driver / Anomaly Detection.

Identifies the significant contributing factors to financial changes.
All detection is deterministic — no LLM.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.agent.state import FinancialInvestigationState, WorkflowStep
from app.services.anomaly_engine import (
    detect_profit_drivers,
    detect_supplier_anomalies,
    detect_expense_anomalies,
    detect_category_margin_changes,
    detect_product_margin_changes,
    detect_general_anomalies,
    detect_duplicate_transactions,
)

logger = logging.getLogger(__name__)


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


def _finding_to_dict(finding) -> dict:
    d = asdict(finding)
    d["verified"] = "unverified"
    return d


def anomaly_detection_node(
    state: FinancialInvestigationState,
    db: Session,
) -> FinancialInvestigationState:
    """
    LangGraph node: Driver / Anomaly Detection.
    Identifies the main contributors to financial changes.
    """
    _trace_step(state, "Detecting contributing factors", "running")

    current_period = state["current_period"]
    comparison_period = state["comparison_period"]
    intent = state.get("intent", "general_financial_investigation")

    try:
        if intent == "profit_change_investigation":
            findings = detect_profit_drivers(db, current_period, comparison_period)

        elif intent == "supplier_analysis_investigation":
            findings = detect_supplier_anomalies(db, current_period, comparison_period)

        elif intent == "expense_change_investigation":
            findings = (
                detect_expense_anomalies(db, current_period, comparison_period)
                + detect_supplier_anomalies(db, current_period, comparison_period)
            )

        elif intent == "product_performance_investigation":
            findings = (
                detect_product_margin_changes(db, current_period, comparison_period)
                + detect_category_margin_changes(db, current_period, comparison_period)
            )

        elif intent == "anomaly_detection_investigation":
            findings = detect_general_anomalies(db, current_period, comparison_period)

        else:
            # General: run all detectors
            findings = detect_profit_drivers(db, current_period, comparison_period)

        # Check for duplicate transactions (always run)
        duplicates = detect_duplicate_transactions(db, current_period)
        if duplicates:
            state["errors"].append(
                f"Potential duplicate transactions detected: {len(duplicates)} group(s)"
            )
            logger.warning("[%s] Duplicates: %d group(s)", state["investigation_id"], len(duplicates))

        findings_dicts = [_finding_to_dict(f) for f in findings]
        state["anomalies"] = findings_dicts

        _trace_step(state, "Detecting contributing factors", "completed",
                    f"{len(findings_dicts)} factor(s) identified")

        logger.info("[%s] Detected %d findings", state["investigation_id"], len(findings_dicts))

    except Exception as exc:
        logger.exception("[%s] Anomaly detection failed", state["investigation_id"])
        state["errors"].append(f"Anomaly detection error: {exc}")
        _trace_step(state, "Detecting contributing factors", "failed", str(exc))

    return state
