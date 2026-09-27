"""Node 5: Evidence Retrieval.

For every significant finding, retrieves the supporting transactions.
Evidence gives the user the ability to inspect underlying records.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agent.state import FinancialInvestigationState, WorkflowStep
from app.services.financial_engine import get_supporting_transactions

logger = logging.getLogger(__name__)

MAX_EVIDENCE_PER_FINDING = 20


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


def _finding_to_evidence(
    finding: dict,
    db: Session,
    current_period: str,
) -> list[dict[str, Any]]:
    """
    Retrieve transactions supporting a finding.
    Maps finding type to appropriate filter parameters.
    """
    finding_type = finding.get("finding_type", "")
    entity = finding.get("entity", "")
    category = finding.get("category", "")

    tx_list: list[dict] = []

    if "supplier_cost" in finding_type:
        # Entity is supplier name
        supplier_name = entity if "Supplier" in entity else finding.get("entity")
        tx_list = get_supporting_transactions(
            db, current_period,
            transaction_type="purchase",
            supplier=supplier_name,
            limit=MAX_EVIDENCE_PER_FINDING,
        )

    elif "refund" in finding_type:
        tx_list = get_supporting_transactions(
            db, current_period,
            transaction_type="refund",
            limit=MAX_EVIDENCE_PER_FINDING,
        )

    elif "product_margin" in finding_type:
        product_name = entity
        tx_list = get_supporting_transactions(
            db, current_period,
            transaction_type="sale",
            product=product_name,
            limit=MAX_EVIDENCE_PER_FINDING,
        )

    elif "expense" in finding_type or "margin" in finding_type or "gross_profit" in finding_type:
        # Use category filter
        cat = category if category not in ("", "Revenue", "Refunds") else None
        if cat:
            tx_list = get_supporting_transactions(
                db, current_period,
                category=cat,
                limit=MAX_EVIDENCE_PER_FINDING,
            )

    elif "revenue" in finding_type:
        tx_list = get_supporting_transactions(
            db, current_period,
            transaction_type="sale",
            limit=MAX_EVIDENCE_PER_FINDING,
        )

    # Attach finding reference to each evidence record
    for tx in tx_list:
        tx["finding_ref"] = f"{finding_type}::{entity}"
        tx["relevance"] = finding.get("reason", "")
        # Serialize date to string if needed
        if hasattr(tx.get("date"), "isoformat"):
            tx["date"] = tx["date"].isoformat()

    return tx_list


def evidence_retrieval_node(
    state: FinancialInvestigationState,
    db: Session,
) -> FinancialInvestigationState:
    """
    LangGraph node: Evidence Retrieval.
    Attaches supporting transaction records to each finding.
    """
    _trace_step(state, "Retrieving supporting evidence", "running")

    current_period = state["current_period"]
    findings = state.get("anomalies", [])

    if not findings:
        _trace_step(state, "Retrieving supporting evidence", "skipped", "No findings to support")
        return state

    all_evidence: list[dict[str, Any]] = []
    seen_tx_ids: set[str] = set()

    for finding in findings:
        evidence_items = _finding_to_evidence(finding, db, current_period)
        # De-duplicate across findings
        for item in evidence_items:
            tx_id = item.get("transaction_id")
            if tx_id and tx_id not in seen_tx_ids:
                seen_tx_ids.add(tx_id)
                all_evidence.append(item)

        # Update supporting_tx_ids on finding if we retrieved live data
        if evidence_items:
            finding["supporting_tx_ids"] = [
                item["transaction_id"] for item in evidence_items
                if item.get("transaction_id")
            ]

    state["evidence"] = all_evidence

    _trace_step(state, "Retrieving supporting evidence", "completed",
                f"{len(all_evidence)} evidence record(s) retrieved")

    logger.info("[%s] Evidence: %d records", state["investigation_id"], len(all_evidence))
    return state
