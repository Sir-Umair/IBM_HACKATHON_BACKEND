"""Investigation routes — run investigations and retrieve results."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from datetime import datetime, timezone
from app.models.api_models import InvestigateRequest, InvestigationResponse, ChatQueryRequest, ChatQueryResponse
from app.models.db_models import Investigation
from app.services.investigation_service import (
    run_investigation,
    get_investigation,
    get_investigation_evidence,
)
from app.services.llm_service import get_llm_service

router = APIRouter(prefix="/api/investigations", tags=["investigations"])
logger = logging.getLogger(__name__)


@router.post("", response_model=InvestigationResponse)
def create_investigation(
    request: InvestigateRequest,
    db: Session = Depends(get_db),
):
    """
    Run a new investigation.
    Executes the full LangGraph workflow synchronously and returns the result.
    """
    logger.info("Investigation requested: %s | %s vs %s",
                request.question, request.current_period, request.comparison_period)

    if request.current_period == request.comparison_period:
        raise HTTPException(
            status_code=400,
            detail="current_period and comparison_period must be different",
        )

    try:
        result = run_investigation(
            db=db,
            question=request.question,
            current_period=request.current_period,
            comparison_period=request.comparison_period,
        )
    except Exception as exc:
        logger.exception("Investigation execution failed")
        raise HTTPException(status_code=500, detail=f"Investigation failed: {exc}")

    # Map state dict → response model
    return _state_to_response(result)


# Also support POST /api/investigate for convenience
from fastapi import APIRouter as _R
investigate_router = _R(prefix="/api", tags=["investigations"])


@investigate_router.post("/investigate", response_model=InvestigationResponse)
def run_investigate(
    request: InvestigateRequest,
    db: Session = Depends(get_db),
):
    """Convenience endpoint matching the spec in the requirements."""
    return create_investigation(request, db)


@router.delete("/{investigation_id}")

def delete_investigation(investigation_id: str, db: Session = Depends(get_db)):
    """Delete an investigation by ID (removes findings and evidence cascade)."""
    record = db.query(Investigation).filter(
        Investigation.investigation_id == investigation_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Investigation {investigation_id} not found")

    db.delete(record)
    db.commit()
    logger.info("Deleted investigation %s", investigation_id)
    return {"status": "deleted", "investigation_id": investigation_id}


@router.post("/{investigation_id}/ask", response_model=ChatQueryResponse)
def ask_investigation_question(
    investigation_id: str,
    payload: ChatQueryRequest,
    db: Session = Depends(get_db),
):
    """
    Interactive Q&A for IBM BOB Hackathon:
    Allows judges/users to ask any follow-up question dynamically against this investigation's findings.
    """
    raw_state = get_investigation(db, investigation_id)
    if not raw_state:
        raise HTTPException(status_code=404, detail=f"Investigation {investigation_id} not found")

    evidence = get_investigation_evidence(db, investigation_id)
    findings = raw_state.get("anomalies", raw_state.get("contributing_factors", []))

    # Format findings with descriptions
    formatted_findings = []
    for f in findings:
        formatted_findings.append({
            "finding_type": f.get("finding_type", ""),
            "entity": f.get("entity", ""),
            "impact": f.get("difference", 0.0),
            "description": f.get("reason", ""),
            "evidence_ids": f.get("supporting_tx_ids", []),
        })

    context = {
        "findings": formatted_findings,
        "metrics": raw_state.get("current_metrics", {}),
        "comparison": raw_state.get("comparison_results", {}),
        "evidence": evidence,
        "current_period": raw_state.get("current_period", "2026-02"),
        "comparison_period": raw_state.get("comparison_period", "2026-01"),
    }

    llm = get_llm_service()
    res = llm.answer_follow_up_question(payload.question, context)
    res["timestamp"] = datetime.now(timezone.utc).isoformat()
    return res


@router.get("/{investigation_id}", response_model=InvestigationResponse)
def retrieve_investigation(investigation_id: str, db: Session = Depends(get_db)):
    """Retrieve a previously-run investigation by ID."""
    result = get_investigation(db, investigation_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Investigation {investigation_id} not found")
    return _state_to_response(result)


@router.get("/{investigation_id}/evidence")
def retrieve_evidence(investigation_id: str, db: Session = Depends(get_db)):
    """Retrieve evidence records for an investigation."""
    # Check investigation exists
    record = db.query(Investigation).filter(
        Investigation.investigation_id == investigation_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Investigation {investigation_id} not found")

    evidence = get_investigation_evidence(db, investigation_id)
    return {"investigation_id": investigation_id, "evidence": evidence}


@router.get("")
def list_investigations(db: Session = Depends(get_db)):

    """List recent investigations."""
    records = db.query(Investigation).order_by(
        Investigation.created_at.desc()
    ).limit(20).all()
    return [
        {
            "investigation_id": r.investigation_id,
            "question": r.question,
            "current_period": r.current_period,
            "comparison_period": r.comparison_period,
            "status": r.status,
            "intent": r.intent,
            "summary": r.summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


def _state_to_response(state: dict) -> InvestigationResponse:
    """Convert investigation state dict to API response model."""
    from app.models.api_models import (
        FindingModel, VerificationModel, WorkflowStep as WS
    )

    findings = []
    for f in state.get("anomalies", state.get("contributing_factors", [])):
        findings.append(FindingModel(
            finding_type=f.get("finding_type", ""),
            category=f.get("category"),
            entity=f.get("entity"),
            impact=f.get("difference"),
            percentage_change=f.get("difference_pct"),
            description=f.get("reason", ""),
            verified=f.get("verified", "unverified"),
            evidence_ids=f.get("supporting_tx_ids", []),
        ))

    checks = state.get("verification_checks", [])
    verification = VerificationModel(
        status=state.get("verification_status", "pending"),
        checks=checks,
        errors=[c.get("message", "") for c in checks if not c.get("passed")],
    )

    workflow = []
    for step in state.get("workflow_trace", []):
        workflow.append(WS(
            step=step.get("step", ""),
            status=step.get("status", ""),
            details=step.get("details"),
        ))

    # Serialize evidence dates
    evidence = []
    for ev in state.get("evidence", []):
        ev_copy = dict(ev)
        if hasattr(ev_copy.get("date"), "isoformat"):
            ev_copy["date"] = ev_copy["date"].isoformat()
        evidence.append(ev_copy)

    return InvestigationResponse(
        investigation_id=state.get("investigation_id", ""),
        status=state.get("status", "completed"),
        question=state.get("question", ""),
        current_period=state.get("current_period", ""),
        comparison_period=state.get("comparison_period", ""),
        intent=state.get("intent"),
        summary=state.get("explanation", "")[:300] if state.get("explanation") else None,
        metrics=state.get("current_metrics", {}),
        comparison=state.get("comparison_results", {}),
        findings=findings,
        evidence=evidence,
        workflow=workflow,
        verification=verification,
        explanation=state.get("explanation"),
        errors=state.get("errors", []),
    )
