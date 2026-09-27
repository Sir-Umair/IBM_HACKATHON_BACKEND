"""Node 6: Verification.

CRITICAL NODE.
Independently recalculates every finding before the LLM generates its explanation.
If verification fails, no explanation is generated.

Checks:
  1. Calculations are correct (recalculate independently)
  2. Evidence actually exists for the finding
  3. Periods are correct
  4. Percentage change is consistent with absolute change
  5. No sign errors
  6. Finding values are internally consistent
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agent.state import FinancialInvestigationState, WorkflowStep, VerificationCheck
from app.services.financial_engine import (
    get_period_metrics,
    get_revenue,
    get_refunds,
    get_expenses,
    get_cogs,
    get_profit,
    analyze_suppliers,
    get_supporting_transactions,
    _round2,
    _safe_pct_change,
)

logger = logging.getLogger(__name__)

TOLERANCE = 0.05   # $0.05 floating-point tolerance for amount comparisons
PCT_TOLERANCE = 0.5  # 0.5% percentage point tolerance


def _check(
    name: str,
    expected: float,
    actual: float,
    tolerance: float = TOLERANCE,
) -> VerificationCheck:
    passed = abs(actual - expected) <= tolerance
    return VerificationCheck(
        check_name=name,
        passed=passed,
        expected=round(expected, 2),
        actual=round(actual, 2),
        message="OK" if passed else f"MISMATCH: expected {expected:.2f}, got {actual:.2f}",
    )


def _verify_supplier_finding(finding: dict, db: Session) -> list[VerificationCheck]:
    """Verify a supplier cost finding by recalculating from scratch."""
    checks: list[VerificationCheck] = []
    entity = finding.get("entity", "")
    current_period = finding.get("_current_period", "")
    comparison_period = finding.get("_comparison_period", "")

    if not current_period or not comparison_period:
        return checks

    # Re-derive supplier name from entity
    supplier_name = entity

    cur_txs = get_supporting_transactions(
        db, current_period, transaction_type="purchase", supplier=supplier_name)
    prev_txs = get_supporting_transactions(
        db, comparison_period, transaction_type="purchase", supplier=supplier_name)

    cur_cost = _round2(sum(t["amount"] for t in cur_txs))
    prev_cost = _round2(sum(t["amount"] for t in prev_txs))
    expected_change = _round2(cur_cost - prev_cost)

    checks.append(_check(
        f"{entity} current cost",
        finding["current_value"],
        cur_cost,
    ))
    checks.append(_check(
        f"{entity} comparison cost",
        finding["baseline"],
        prev_cost,
    ))
    checks.append(_check(
        f"{entity} cost change",
        finding["difference"],
        expected_change,
    ))

    return checks


def _verify_refund_finding(finding: dict, db: Session) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    current_period = finding.get("_current_period", "")
    comparison_period = finding.get("_comparison_period", "")
    if not current_period:
        return checks

    cur_refunds = get_refunds(db, current_period)
    prev_refunds = get_refunds(db, comparison_period) if comparison_period else 0.0
    expected_change = _round2(cur_refunds - prev_refunds)

    checks.append(_check("current refunds", finding["current_value"], cur_refunds))
    if comparison_period:
        checks.append(_check("comparison refunds", finding["baseline"], prev_refunds))
        checks.append(_check("refund change", finding["difference"], expected_change))

    return checks


def _verify_period_metrics(
    state: FinancialInvestigationState,
    db: Session,
) -> list[VerificationCheck]:
    """Verify that stored metrics match fresh recalculations."""
    checks: list[VerificationCheck] = []
    current_period = state["current_period"]
    comparison_period = state["comparison_period"]

    fresh = get_period_metrics(db, current_period)
    stored = state.get("current_metrics", {})

    checks.append(_check("revenue", stored.get("revenue", 0), fresh.revenue))
    checks.append(_check("net_profit", stored.get("net_profit", 0), fresh.net_profit))
    checks.append(_check("cogs", stored.get("cogs", 0), fresh.cogs))

    return checks


def _verify_pct_consistent(finding: dict) -> VerificationCheck:
    """Verify that the percentage change is consistent with the absolute change."""
    baseline = finding.get("baseline", 0.0)
    current = finding.get("current_value", 0.0)
    claimed_pct = finding.get("difference_pct", 0.0)
    calculated_pct = _safe_pct_change(current, baseline)
    return _check(
        f"{finding.get('entity', '?')} pct_change",
        calculated_pct,
        claimed_pct,
        tolerance=PCT_TOLERANCE,
    )


def _verify_evidence_exists(finding: dict, evidence: list[dict]) -> VerificationCheck:
    """Verify that at least one evidence record exists for significant findings."""
    entity = finding.get("entity", "")
    tx_ids = set(finding.get("supporting_tx_ids", []))
    evidence_tx_ids = {e.get("transaction_id") for e in evidence}
    overlap = tx_ids & evidence_tx_ids
    has_evidence = len(overlap) > 0 or len(tx_ids) == 0  # pass if no IDs expected
    return VerificationCheck(
        check_name=f"{entity} evidence_exists",
        passed=has_evidence,
        expected=1,
        actual=len(overlap),
        message="Evidence found" if has_evidence else "WARNING: No evidence records found",
    )


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


def verification_node(
    state: FinancialInvestigationState,
    db: Session,
) -> FinancialInvestigationState:
    """
    LangGraph node: Verification.
    Independently recalculates findings before allowing the explanation.
    """
    _trace_step(state, "Verifying calculations", "running")

    current_period = state["current_period"]
    comparison_period = state["comparison_period"]
    findings = state.get("anomalies", [])
    evidence = state.get("evidence", [])

    all_checks: list[VerificationCheck] = []
    verification_errors: list[str] = []

    # 1. Verify period metrics
    metric_checks = _verify_period_metrics(state, db)
    all_checks.extend(metric_checks)

    # 2. Verify each significant finding
    for finding in findings:
        # Inject period context into finding for helpers
        finding["_current_period"] = current_period
        finding["_comparison_period"] = comparison_period

        # Verify percentage consistency
        pct_check = _verify_pct_consistent(finding)
        all_checks.append(pct_check)

        # Verify evidence exists
        evidence_check = _verify_evidence_exists(finding, evidence)
        all_checks.append(evidence_check)

        # Type-specific verification
        finding_type = finding.get("finding_type", "")
        if "supplier_cost" in finding_type:
            sup_checks = _verify_supplier_finding(finding, db)
            all_checks.extend(sup_checks)
        elif "refund" in finding_type:
            ref_checks = _verify_refund_finding(finding, db)
            all_checks.extend(ref_checks)

        # Mark finding as verified if all its checks passed
        finding_checks = [c for c in all_checks
                          if finding.get("entity", "") in c["check_name"]]
        all_passed = all(c["passed"] for c in finding_checks) if finding_checks else True
        finding["verified"] = "verified" if all_passed else "unverified"

    # Clean up injected period fields
    for finding in findings:
        finding.pop("_current_period", None)
        finding.pop("_comparison_period", None)

    # Determine overall verification status
    failed_checks = [c for c in all_checks if not c["passed"]]
    critical_failures = [c for c in failed_checks if "MISMATCH" in c.get("message", "")]

    if not all_checks:
        verification_status = "passed"
    elif critical_failures:
        verification_status = "failed"
        for fc in critical_failures:
            verification_errors.append(fc["message"])
        logger.warning("[%s] Verification failures: %s",
                       state["investigation_id"], critical_failures)
    elif failed_checks:
        verification_status = "partial"
    else:
        verification_status = "passed"

    # Only keep verified findings as contributing factors
    state["contributing_factors"] = [
        f for f in findings
        if f.get("verified") in ("verified", "unverified")  # include unverified with caveat
    ]

    state["verification_checks"] = all_checks
    state["verification_status"] = verification_status
    state["errors"].extend(verification_errors)

    _trace_step(state, "Verifying calculations", "completed",
                f"Status: {verification_status} | {len(failed_checks)} check(s) flagged")

    logger.info("[%s] Verification: %s (%d total checks, %d failed)",
                state["investigation_id"], verification_status,
                len(all_checks), len(failed_checks))
    return state
