"""
LangGraph Investigation Graph.

Orchestrates the full investigation workflow:

START
  ↓
Intent Analyzer
  ↓
Investigation Planner
  ↓
Financial Analysis
  ↓
Driver / Anomaly Detection
  ↓
Evidence Retrieval
  ↓
Verification
  ↓
Explanation Generator
  ↓
END

The DB session is injected via functools.partial so that nodes
remain pure functions compatible with LangGraph's node API.
"""

from __future__ import annotations

import logging
from functools import partial

from langgraph.graph import StateGraph, END

from app.agent.state import FinancialInvestigationState
from app.agent.nodes.intent import intent_analyzer_node
from app.agent.nodes.planner import investigation_planner_node
from app.agent.nodes.analysis import financial_analysis_node
from app.agent.nodes.anomaly import anomaly_detection_node
from app.agent.nodes.evidence import evidence_retrieval_node
from app.agent.nodes.verification import verification_node
from app.agent.nodes.explanation import explanation_node

logger = logging.getLogger(__name__)


def _route_after_verification(state: FinancialInvestigationState) -> str:
    """
    Conditional edge: decide whether to proceed to explanation.
    If verification completely failed, we still run explanation
    so it can produce the failure message (it handles this case internally).
    """
    return "generate_explanation"


def build_investigation_graph(db) -> StateGraph:
    """
    Build and compile the LangGraph investigation graph.

    db: SQLAlchemy Session — injected into nodes that need database access.
    """
    graph = StateGraph(FinancialInvestigationState)

    # Nodes that only need state (no DB)
    graph.add_node("intent_analyzer", intent_analyzer_node)
    graph.add_node("investigation_planner", investigation_planner_node)

    # Nodes that need DB — inject via partial
    graph.add_node("financial_analysis", partial(financial_analysis_node, db=db))
    graph.add_node("anomaly_detection", partial(anomaly_detection_node, db=db))
    graph.add_node("evidence_retrieval", partial(evidence_retrieval_node, db=db))
    graph.add_node("verification", partial(verification_node, db=db))

    # Explanation node (optionally uses LLM via config)
    graph.add_node("generate_explanation", explanation_node)

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.set_entry_point("intent_analyzer")
    graph.add_edge("intent_analyzer", "investigation_planner")
    graph.add_edge("investigation_planner", "financial_analysis")
    graph.add_edge("financial_analysis", "anomaly_detection")
    graph.add_edge("anomaly_detection", "evidence_retrieval")
    graph.add_edge("evidence_retrieval", "verification")

    # Conditional: after verification, always go to explanation
    # (explanation handles the verification-failed case internally)
    graph.add_conditional_edges(
        "verification",
        _route_after_verification,
        {"generate_explanation": "generate_explanation"},
    )
    graph.add_edge("generate_explanation", END)

    return graph.compile()
