"""
Investigation Service.

Orchestrates the LangGraph workflow for a single investigation request.
Stores results in SQLite.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agent.graph import build_investigation_graph
from app.agent.state import initial_state
from app.models.db_models import Investigation, InvestigationFinding, EvidenceRecord
from app.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


def run_investigation(
    db: Session,
    question: str,
    current_period: str,
    comparison_period: str,
) -> dict[str, Any]:
    """
    Run the full LangGraph investigation workflow.

    Returns the completed investigation state as a dict.
    Also persists the investigation and findings to SQLite.
    """
    investigation_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
    logger.info("[%s] Starting investigation: %s", investigation_id, question)

    # Persist initial record
    db_investigation = Investigation(
        investigation_id=investigation_id,
        question=question,
        current_period=current_period,
        comparison_period=comparison_period,
        status="running",
    )
    db.add(db_investigation)
    db.commit()

    try:
        # Build initial state
        state = initial_state(
            question=question,
            current_period=current_period,
            comparison_period=comparison_period,
            investigation_id=investigation_id,
        )

        # Build graph (injects DB session into nodes)
        graph = build_investigation_graph(db)

        # Run the graph (LLM service injected via config)
        llm_service = get_llm_service()
        config = {
            "configurable": {
                "llm_service": llm_service if llm_service.is_available else None,
            }
        }

        final_state = graph.invoke(state, config=config)

        # Persist findings
        for finding in final_state.get("anomalies", []):
            tx_ids = ",".join(finding.get("supporting_tx_ids", []))
            db_finding = InvestigationFinding(
                investigation_id=investigation_id,
                finding_type=finding.get("finding_type", ""),
                category=finding.get("category", ""),
                entity=finding.get("entity", ""),
                impact=finding.get("difference"),
                percentage_change=finding.get("difference_pct"),
                description=finding.get("reason", ""),
                verified=finding.get("verified", "unverified"),
                evidence_ids=tx_ids,
            )
            db.add(db_finding)

        # Persist evidence records
        for ev in final_state.get("evidence", []):
            db_ev = EvidenceRecord(
                investigation_id=investigation_id,
                finding_ref=ev.get("finding_ref"),
                transaction_id=ev.get("transaction_id", ""),
                relevance=ev.get("relevance"),
            )
            db.add(db_ev)

        # Build summary from first finding
        findings = final_state.get("contributing_factors", final_state.get("anomalies", []))
        summary = ""
        if findings:
            top = findings[0]
            summary = top.get("reason", "")

        # Update investigation record
        db_investigation.status = final_state.get("status", "completed")
        db_investigation.intent = final_state.get("intent", "")
        db_investigation.summary = summary
        db_investigation.result_json = json.dumps(_serializable(final_state))
        db_investigation.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("[%s] Investigation completed: %s", investigation_id, final_state.get("status"))
        return _serializable(final_state)

    except Exception as exc:
        logger.exception("[%s] Investigation failed with exception", investigation_id)
        db_investigation.status = "failed"
        db_investigation.result_json = json.dumps({"error": str(exc)})
        db_investigation.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise


def _serializable(state: dict) -> dict:
    """Recursively convert non-serializable objects to JSON-safe types."""
    import dataclasses
    import decimal

    def convert(obj):
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if hasattr(obj, "isoformat"):  # date/datetime
            return obj.isoformat()
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return {k: convert(v) for k, v in dataclasses.asdict(obj).items()}
        if isinstance(obj, dict):
            return {str(k): convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [convert(i) for i in obj]
        if isinstance(obj, set):
            return [convert(i) for i in sorted(obj, key=str)]
        try:
            return str(obj)
        except Exception:
            return None

    return convert(dict(state))


def get_investigation(db: Session, investigation_id: str) -> dict[str, Any] | None:
    """Retrieve a stored investigation result."""
    record = db.query(Investigation).filter(
        Investigation.investigation_id == investigation_id
    ).first()
    if not record:
        return None
    if record.result_json:
        return json.loads(record.result_json)
    return {
        "investigation_id": investigation_id,
        "status": record.status,
        "question": record.question,
        "current_period": record.current_period,
        "comparison_period": record.comparison_period,
    }


def get_investigation_evidence(db: Session, investigation_id: str) -> list[dict[str, Any]]:
    """Retrieve evidence records for an investigation."""
    records = db.query(EvidenceRecord).filter(
        EvidenceRecord.investigation_id == investigation_id
    ).all()
    return [
        {
            "id": r.id,
            "investigation_id": r.investigation_id,
            "finding_ref": r.finding_ref,
            "transaction_id": r.transaction_id,
            "relevance": r.relevance,
        }
        for r in records
    ]
