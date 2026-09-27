"""Node 1: Intent Analyzer.

Understands what the user is asking and extracts:
  - intent type
  - current_period (if mentioned)
  - comparison_period (if mentioned)
  - named entities (suppliers, products)

The LLM is used here for NLU only; no financial calculations.
Falls back to rule-based detection if LLM is unavailable.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from app.agent.state import FinancialInvestigationState, WorkflowStep

logger = logging.getLogger(__name__)

# ─── Intent mapping ───────────────────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "profit_change_investigation": [
        "profit", "net income", "bottom line", "earnings",
    ],
    "revenue_change_investigation": [
        "revenue", "sales", "income", "turnover", "top line",
    ],
    "expense_change_investigation": [
        "expense", "cost", "spending", "expenditure", "overhead",
    ],
    "margin_change_investigation": [
        "margin", "gross margin", "markup", "profitability",
    ],
    "refund_change_investigation": [
        "refund", "return", "chargeback", "reversal",
    ],
    "supplier_analysis_investigation": [
        "supplier", "vendor", "provider", "sourcing",
    ],
    "product_performance_investigation": [
        "product", "item", "sku", "merchandise",
    ],
    "anomaly_detection_investigation": [
        "unusual", "anomaly", "strange", "unexpected", "suspicious",
        "duplicate", "spike", "outlier",
    ],
}

MONTH_MAP: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
}


def _rule_based_intent(question: str) -> str:
    """Detect intent using keyword matching. Returns most specific match."""
    q = question.lower()

    # High-specificity multi-word patterns (checked first)
    if ("revenue" in q or "sales" in q) and ("profit" in q or "loss" in q):
        return "profit_change_investigation"

    # Supplier-specific patterns checked before generic expense
    if "supplier" in q or "vendor" in q:
        return "supplier_analysis_investigation"

    # Product-specific patterns checked before generic margin
    if "product" in q or "item" in q or "sku" in q:
        return "product_performance_investigation"

    # Intent-specific keyword scan in priority order
    PRIORITY_ORDER = [
        "anomaly_detection_investigation",
        "profit_change_investigation",
        "margin_change_investigation",
        "refund_change_investigation",
        "revenue_change_investigation",
        "expense_change_investigation",
        "supplier_analysis_investigation",
        "product_performance_investigation",
        "general_financial_investigation",
    ]
    for intent in PRIORITY_ORDER:
        keywords = INTENT_KEYWORDS.get(intent, [])
        if any(kw in q for kw in keywords):
            return intent

    return "general_financial_investigation"


def _extract_period_from_text(question: str, default_year: int = 2026) -> tuple[str | None, str | None]:
    """Extract (current_period, comparison_period) from question text."""
    q = question.lower()
    found_months: list[str] = []

    # Match full month names or abbreviations
    for month_name, month_num in sorted(MONTH_MAP.items(), key=lambda x: -len(x[0])):
        if month_name in q:
            found_months.append(f"{default_year}-{month_num}")

    # Match YYYY-MM patterns
    yyyy_mm = re.findall(r"\b(\d{4}-\d{2})\b", question)
    for ym in yyyy_mm:
        if ym not in found_months:
            found_months.append(ym)

    if len(found_months) >= 2:
        return found_months[0], found_months[1]
    if len(found_months) == 1:
        return found_months[0], None
    return None, None


def _extract_entities(question: str) -> dict[str, Any]:
    """Extract named entities: supplier/product names."""
    entities: dict[str, Any] = {}

    # Look for "Supplier X" or "Supplier A/B/C" patterns
    supplier_matches = re.findall(r"supplier\s+([A-Za-z0-9_\-]+)", question, re.IGNORECASE)
    if supplier_matches:
        entities["suppliers"] = [f"Supplier {m.upper()}" if len(m) == 1 else m
                                  for m in supplier_matches]

    # Look for product-like names (Title Case words near "product" keyword)
    product_matches = re.findall(r"product\s+([A-Za-z0-9_\-]+)", question, re.IGNORECASE)
    if product_matches:
        entities["products"] = product_matches

    return entities


def _trace_step(state: FinancialInvestigationState, step: str, status: str, details: str = "") -> None:
    state["workflow_trace"].append(WorkflowStep(step=step, status=status, details=details))


# ─── LLM-assisted intent (with fallback) ─────────────────────────────────────

def _llm_analyze_intent(
    question: str,
    current_period: str,
    comparison_period: str,
    llm_service: Any | None,
) -> dict[str, Any]:
    """Call LLM for intent analysis. Returns dict with intent + entities."""
    if llm_service is None:
        return {}
    try:
        result = llm_service.analyze_intent(
            question=question,
            current_period=current_period,
            comparison_period=comparison_period,
        )
        return result or {}
    except Exception as exc:
        logger.warning("LLM intent analysis failed, using rule-based fallback: %s", exc)
        return {}


# ─── Node function ────────────────────────────────────────────────────────────

def intent_analyzer_node(state: FinancialInvestigationState, config: RunnableConfig | None = None) -> FinancialInvestigationState:
    """
    LangGraph node: Intent Analyzer.
    Determines what the user is asking and which periods to compare.
    """
    _trace_step(state, "Understanding question", "running")
    question = state["question"]
    current_period = state["current_period"]
    comparison_period = state["comparison_period"]

    # Try to get LLM service from config
    llm_service = (config or {}).get("configurable", {}).get("llm_service")

    # 1. Rule-based intent (always available)
    rule_intent = _rule_based_intent(question)
    rule_entities = _extract_entities(question)

    # 2. Period extraction from question text (supplement state periods)
    text_current, text_comparison = _extract_period_from_text(question)
    if text_current and not current_period:
        current_period = text_current
        state["current_period"] = current_period
    if text_comparison and not comparison_period:
        comparison_period = text_comparison
        state["comparison_period"] = comparison_period

    # 3. Optional LLM enhancement
    llm_result = _llm_analyze_intent(question, current_period, comparison_period, llm_service)
    intent = llm_result.get("intent") or rule_intent
    entities = {**rule_entities, **llm_result.get("entities", {})}

    state["intent"] = intent
    state["entities"] = entities

    _trace_step(state, "Understanding question", "completed",
                f"Intent: {intent} | Period: {current_period} vs {comparison_period}")

    logger.info("[%s] Intent: %s | %s vs %s",
                state["investigation_id"], intent, current_period, comparison_period)
    return state
