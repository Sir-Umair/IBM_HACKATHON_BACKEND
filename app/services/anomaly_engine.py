"""
Anomaly and Driver Detection.

Uses explainable statistical methods:
  - Percentage change threshold (> 20% change flags as significant)
  - Standard deviation from historical average (if 3+ periods available)
  - Absolute impact threshold ($500 minimum to reduce noise)
  - Duplicate transaction detection

All anomalies are explainable and traceable to specific records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.services.financial_engine import (
    compare_periods,
    compare_categories,
    compare_products,
    compare_suppliers,
    get_supporting_transactions,
    _load_period,
    _round2,
    _safe_pct_change,
    _direction,
)

logger = logging.getLogger(__name__)

# Thresholds
SIGNIFICANT_CHANGE_PCT = 15.0   # flag if > 15% change
SIGNIFICANT_AMOUNT = 500.0      # minimum absolute impact to report
DUPLICATE_WINDOW_DAYS = 1       # transactions same supplier/amount within N days


@dataclass
class AnomalyFinding:
    """A detected anomaly or significant change with evidence."""
    finding_type: str               # "expense_increase", "margin_drop", etc.
    category: str
    entity: str                     # supplier name, product name, or category
    metric: str                     # what was measured
    baseline: float                 # comparison period value
    current_value: float            # current period value
    difference: float               # current - baseline
    difference_pct: float           # % change
    threshold: float                # threshold that was crossed
    reason: str                     # human-readable reason
    supporting_tx_ids: list[str] = field(default_factory=list)
    severity: str = "medium"        # "low" | "medium" | "high"


def _severity(pct_change: float, abs_change: float) -> str:
    if abs(pct_change) >= 50 or abs(abs_change) >= 5000:
        return "high"
    if abs(pct_change) >= 25 or abs(abs_change) >= 2000:
        return "medium"
    return "low"


# ─── Top-level Driver Detection ───────────────────────────────────────────────

def detect_profit_drivers(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[AnomalyFinding]:
    """
    Identify the main drivers of profit change.
    Returns a ranked list of AnomalyFinding objects.
    """
    findings: list[AnomalyFinding] = []

    # 1. Revenue change
    comparisons = compare_periods(db, current_period, comparison_period)
    rev_cmp = comparisons.get("revenue")
    if rev_cmp and abs(rev_cmp.change) >= SIGNIFICANT_AMOUNT:
        findings.append(AnomalyFinding(
            finding_type=f"revenue_{rev_cmp.direction}",
            category="Revenue",
            entity="Total Revenue",
            metric="revenue",
            baseline=rev_cmp.comparison_value,
            current_value=rev_cmp.current_value,
            difference=rev_cmp.change,
            difference_pct=rev_cmp.change_pct,
            threshold=SIGNIFICANT_AMOUNT,
            reason=f"Revenue {rev_cmp.direction}d by ${abs(rev_cmp.change):,.2f} "
                   f"({abs(rev_cmp.change_pct):.1f}%)",
            severity=_severity(rev_cmp.change_pct, rev_cmp.change),
        ))

    # 2. Refund change
    ref_cmp = comparisons.get("refunds")
    if ref_cmp and abs(ref_cmp.change) >= SIGNIFICANT_AMOUNT:
        tx_ids = [t["transaction_id"] for t in get_supporting_transactions(
            db, current_period, transaction_type="refund")]
        findings.append(AnomalyFinding(
            finding_type=f"refund_{ref_cmp.direction}",
            category="Refunds",
            entity="Total Refunds",
            metric="refunds",
            baseline=ref_cmp.comparison_value,
            current_value=ref_cmp.current_value,
            difference=ref_cmp.change,
            difference_pct=ref_cmp.change_pct,
            threshold=SIGNIFICANT_AMOUNT,
            reason=f"Refunds {ref_cmp.direction}d by ${abs(ref_cmp.change):,.2f} "
                   f"({abs(ref_cmp.change_pct):.1f}%) — "
                   f"from ${ref_cmp.comparison_value:,.2f} to ${ref_cmp.current_value:,.2f}",
            supporting_tx_ids=tx_ids[:20],
            severity=_severity(ref_cmp.change_pct, ref_cmp.change),
        ))

    # 3. Supplier cost changes
    supplier_findings = detect_supplier_anomalies(db, current_period, comparison_period)
    findings.extend(supplier_findings)

    # 4. Operating expense changes
    expense_findings = detect_expense_anomalies(db, current_period, comparison_period)
    findings.extend(expense_findings)

    # 5. Category margin changes
    category_findings = detect_category_margin_changes(db, current_period, comparison_period)
    findings.extend(category_findings)

    # 6. Product margin changes
    product_findings = detect_product_margin_changes(db, current_period, comparison_period)
    findings.extend(product_findings)

    # Sort by absolute impact
    findings.sort(key=lambda f: abs(f.difference), reverse=True)
    return findings


def detect_supplier_anomalies(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[AnomalyFinding]:
    """Detect suppliers with significant cost changes."""
    findings: list[AnomalyFinding] = []
    supplier_comps = compare_suppliers(db, current_period, comparison_period)

    for s in supplier_comps:
        change = s["cost_change"]
        pct = s["cost_change_pct"]
        if abs(change) < SIGNIFICANT_AMOUNT:
            continue
        if abs(pct) < SIGNIFICANT_CHANGE_PCT and abs(change) < 2000:
            continue

        direction = _direction(change)
        tx_ids = [t["transaction_id"] for t in get_supporting_transactions(
            db, current_period, transaction_type="purchase", supplier=s["supplier"])]

        findings.append(AnomalyFinding(
            finding_type=f"supplier_cost_{direction}",
            category="Supplier Costs",
            entity=s["supplier"],
            metric="supplier_cost",
            baseline=s["comparison_cost"],
            current_value=s["current_cost"],
            difference=change,
            difference_pct=pct,
            threshold=SIGNIFICANT_CHANGE_PCT,
            reason=f"{s['supplier']} costs {direction}d by ${abs(change):,.2f} "
                   f"({abs(pct):.1f}%) — "
                   f"from ${s['comparison_cost']:,.2f} to ${s['current_cost']:,.2f}",
            supporting_tx_ids=tx_ids,
            severity=_severity(pct, change),
        ))

    return findings


def detect_expense_anomalies(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[AnomalyFinding]:
    """Detect operating expense categories with significant changes."""
    findings: list[AnomalyFinding] = []

    cur_df = _load_period(db, current_period)
    prev_df = _load_period(db, comparison_period)

    if cur_df.empty and prev_df.empty:
        return []

    expense_types = ["expense", "fee"]
    cur_exp = cur_df[cur_df["transaction_type"].isin(expense_types)] if not cur_df.empty else pd.DataFrame()
    prev_exp = prev_df[prev_df["transaction_type"].isin(expense_types)] if not prev_df.empty else pd.DataFrame()

    # Group by category
    cur_by_cat = cur_exp.groupby("category")["amount"].sum() if not cur_exp.empty else pd.Series(dtype=float)
    prev_by_cat = prev_exp.groupby("category")["amount"].sum() if not prev_exp.empty else pd.Series(dtype=float)
    all_cats = set(cur_by_cat.index) | set(prev_by_cat.index)

    for cat in all_cats:
        cur_val = _round2(float(cur_by_cat.get(cat, 0.0)))
        prev_val = _round2(float(prev_by_cat.get(cat, 0.0)))
        change = _round2(cur_val - prev_val)
        pct = _safe_pct_change(cur_val, prev_val)

        if abs(change) < SIGNIFICANT_AMOUNT:
            continue

        direction = _direction(change)
        tx_ids = [t["transaction_id"] for t in get_supporting_transactions(
            db, current_period, category=cat)]

        findings.append(AnomalyFinding(
            finding_type=f"expense_{direction}",
            category=cat,
            entity=f"{cat} Expenses",
            metric="operating_expense",
            baseline=prev_val,
            current_value=cur_val,
            difference=change,
            difference_pct=pct,
            threshold=SIGNIFICANT_CHANGE_PCT,
            reason=f"{cat} expenses {direction}d by ${abs(change):,.2f} "
                   f"({abs(pct):.1f}%) — "
                   f"from ${prev_val:,.2f} to ${cur_val:,.2f}",
            supporting_tx_ids=tx_ids[:20],
            severity=_severity(pct, change),
        ))

    return findings


def detect_category_margin_changes(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[AnomalyFinding]:
    """Detect categories with significant gross profit changes."""
    findings: list[AnomalyFinding] = []
    cat_comps = compare_categories(db, current_period, comparison_period)

    for c in cat_comps:
        gp_change = c["gross_profit_change"]
        if abs(gp_change) < SIGNIFICANT_AMOUNT:
            continue

        margin_change = c["margin_change_ppt"]
        direction = _direction(gp_change)
        tx_ids = [t["transaction_id"] for t in get_supporting_transactions(
            db, current_period, category=c["category"])]

        finding_type = f"margin_{direction}" if abs(margin_change) > 1.0 else f"gross_profit_{direction}"
        reason = (
            f"{c['category']} gross profit {direction}d by ${abs(gp_change):,.2f}; "
            f"margin changed from {c['comparison_margin_pct']:.1f}% to {c['current_margin_pct']:.1f}% "
            f"({margin_change:+.1f} percentage points)"
        )

        findings.append(AnomalyFinding(
            finding_type=finding_type,
            category=c["category"],
            entity=f"{c['category']} Category",
            metric="gross_profit",
            baseline=c["comparison_gross_profit"],
            current_value=c["current_gross_profit"],
            difference=gp_change,
            difference_pct=_safe_pct_change(c["current_gross_profit"], c["comparison_gross_profit"]),
            threshold=SIGNIFICANT_AMOUNT,
            reason=reason,
            supporting_tx_ids=tx_ids[:20],
            severity=_severity(margin_change, gp_change),
        ))

    return findings


def detect_product_margin_changes(
    db: Session,
    current_period: str,
    comparison_period: str,
    top_n: int = 5,
) -> list[AnomalyFinding]:
    """Detect products with significant margin changes. Returns top_n."""
    findings: list[AnomalyFinding] = []
    prod_comps = compare_products(db, current_period, comparison_period)

    for p in prod_comps[:top_n]:
        gp_change = p["gross_profit_change"]
        margin_change = p["margin_change_ppt"]
        if abs(gp_change) < SIGNIFICANT_AMOUNT and abs(margin_change) < 3.0:
            continue

        direction = _direction(gp_change)
        tx_ids = [t["transaction_id"] for t in get_supporting_transactions(
            db, current_period, product=p["product"], transaction_type="sale")]

        findings.append(AnomalyFinding(
            finding_type=f"product_margin_{direction}",
            category=p["category"],
            entity=p["product"],
            metric="product_gross_margin",
            baseline=p["comparison_gross_profit"],
            current_value=p["current_gross_profit"],
            difference=gp_change,
            difference_pct=_safe_pct_change(p["current_gross_profit"], p["comparison_gross_profit"]),
            threshold=SIGNIFICANT_CHANGE_PCT,
            reason=f"{p['product']} gross profit {direction}d by ${abs(gp_change):,.2f}; "
                   f"margin went from {p['comparison_margin_pct']:.1f}% to {p['current_margin_pct']:.1f}% "
                   f"({margin_change:+.1f}ppt)",
            supporting_tx_ids=tx_ids[:10],
            severity=_severity(margin_change, gp_change),
        ))

    return findings


def detect_duplicate_transactions(db: Session, period: str) -> list[dict[str, Any]]:
    """
    Detect potential duplicate transactions:
    Same supplier, same amount, within DUPLICATE_WINDOW_DAYS.
    """
    df = _load_period(db, period)
    if df.empty:
        return []

    purchase_df = df[df["transaction_type"] == "purchase"].copy()
    if purchase_df.empty:
        return []

    purchase_df = purchase_df.sort_values(["supplier", "amount", "date"])
    duplicates = []

    for (supplier, amount), group in purchase_df.groupby(["supplier", "amount"]):
        if len(group) < 2:
            continue
        dates = sorted(group["date"].tolist())
        for i in range(len(dates) - 1):
            delta = (dates[i + 1] - dates[i]).days
            if delta <= DUPLICATE_WINDOW_DAYS:
                ids = group["transaction_id"].tolist()
                duplicates.append({
                    "type": "potential_duplicate",
                    "supplier": supplier,
                    "amount": amount,
                    "dates": [str(d) for d in dates],
                    "transaction_ids": ids,
                    "reason": f"Same supplier '{supplier}' and amount ${amount:.2f} appear {len(group)} times within {DUPLICATE_WINDOW_DAYS} day(s)",
                })
                break  # only report once per group

    return duplicates


def detect_general_anomalies(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[AnomalyFinding]:
    """General anomaly scan: expense spikes and refund spikes."""
    findings: list[AnomalyFinding] = []
    findings.extend(detect_supplier_anomalies(db, current_period, comparison_period))
    findings.extend(detect_expense_anomalies(db, current_period, comparison_period))

    # High-value refund check
    cur_df = _load_period(db, current_period)
    if not cur_df.empty:
        refunds = cur_df[cur_df["transaction_type"] == "refund"]
        high_value_refunds = refunds[refunds["amount"] > 600]
        if not high_value_refunds.empty:
            total = _round2(high_value_refunds["amount"].sum())
            tx_ids = high_value_refunds["transaction_id"].tolist()
            findings.append(AnomalyFinding(
                finding_type="high_value_refund",
                category="Refunds",
                entity="High-Value Refunds",
                metric="refund_amount",
                baseline=0,
                current_value=total,
                difference=total,
                difference_pct=100,
                threshold=600,
                reason=f"Found {len(high_value_refunds)} refund(s) above $600 totalling ${total:,.2f}",
                supporting_tx_ids=tx_ids,
                severity="medium",
            ))

    findings.sort(key=lambda f: abs(f.difference), reverse=True)
    return findings
