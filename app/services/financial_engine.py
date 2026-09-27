"""
Deterministic Financial Engine.

All financial calculations are performed here using Pandas/SQL.
The LLM MUST NOT perform any of these calculations.

Formulas documented:
  Net Revenue   = SUM(sales.amount) - SUM(refunds.amount)
  COGS          = SUM(sales.cost) where cost IS NOT NULL
  Gross Profit  = Net Revenue - COGS
  Gross Margin  = Gross Profit / Net Revenue  (if Net Revenue > 0)
  Total Expenses= SUM(purchases.amount) + SUM(expenses.amount) + SUM(fees.amount)
  Net Profit    = Net Revenue - COGS - Total Expenses
  Refund Rate   = SUM(refunds) / SUM(gross sales)  (if sales > 0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models.db_models import Transaction

logger = logging.getLogger(__name__)


# ─── Data Types ───────────────────────────────────────────────────────────────

@dataclass
class PeriodMetrics:
    period: str
    revenue: float = 0.0           # gross sales
    refunds: float = 0.0           # total refunds
    net_revenue: float = 0.0       # revenue - refunds
    cogs: float = 0.0              # cost of goods sold
    gross_profit: float = 0.0      # net_revenue - cogs
    gross_margin_pct: float = 0.0  # gross_profit / net_revenue * 100
    purchases: float = 0.0         # supplier purchases
    expenses: float = 0.0          # operating expenses
    fees: float = 0.0              # fees
    total_costs: float = 0.0       # purchases + expenses + fees
    net_profit: float = 0.0        # net_revenue - cogs - total_costs
    refund_rate_pct: float = 0.0   # refunds / revenue * 100
    transaction_count: int = 0


@dataclass
class PeriodComparison:
    metric: str
    current_period: str
    comparison_period: str
    current_value: float
    comparison_value: float
    change: float                  # current - comparison
    change_pct: float              # change / |comparison| * 100 (or 0 if comparison==0)
    direction: str                 # "increase" | "decrease" | "unchanged"


@dataclass
class CategoryMetrics:
    period: str
    category: str
    revenue: float = 0.0
    cogs: float = 0.0
    gross_profit: float = 0.0
    gross_margin_pct: float = 0.0
    refunds: float = 0.0
    transaction_count: int = 0


@dataclass
class ProductMetrics:
    period: str
    product: str
    category: str
    revenue: float = 0.0
    cogs: float = 0.0
    gross_profit: float = 0.0
    gross_margin_pct: float = 0.0
    quantity: float = 0.0
    unit_count: int = 0


@dataclass
class SupplierMetrics:
    period: str
    supplier: str
    total_cost: float = 0.0
    transaction_count: int = 0
    categories: list[str] = field(default_factory=list)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_period(db: Session, period: str) -> pd.DataFrame:
    """Load all transactions for a period into a DataFrame."""
    rows = db.query(Transaction).filter(Transaction.period == period).all()
    if not rows:
        return pd.DataFrame(columns=[
            "id", "transaction_id", "date", "transaction_type",
            "category", "subcategory", "description", "amount",
            "quantity", "unit_price", "cost", "customer",
            "supplier", "product", "status", "period",
        ])
    data = []
    for r in rows:
        data.append({
            "id": r.id,
            "transaction_id": r.transaction_id,
            "date": r.date,
            "transaction_type": r.transaction_type,
            "category": r.category,
            "subcategory": r.subcategory,
            "description": r.description,
            "amount": r.amount or 0.0,
            "quantity": r.quantity or 1.0,
            "unit_price": r.unit_price,
            "cost": r.cost,
            "customer": r.customer,
            "supplier": r.supplier,
            "product": r.product,
            "status": r.status,
            "period": r.period,
        })
    return pd.DataFrame(data)


def _safe_pct_change(new_val: float, old_val: float) -> float:
    """Return percentage change; 0.0 if old_val is zero."""
    if old_val == 0:
        return 0.0
    return round((new_val - old_val) / abs(old_val) * 100, 2)


def _direction(change: float) -> str:
    if change > 0.001:
        return "increase"
    if change < -0.001:
        return "decrease"
    return "unchanged"


def _round2(v: float) -> float:
    return round(v, 2)


# ─── Core Metric Functions ────────────────────────────────────────────────────

def get_revenue(db: Session, period: str) -> float:
    """Sum of all sale transaction amounts for the period."""
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    return _round2(df[df["transaction_type"] == "sale"]["amount"].sum())


def get_refunds(db: Session, period: str) -> float:
    """Sum of all refund transaction amounts for the period."""
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    return _round2(df[df["transaction_type"] == "refund"]["amount"].sum())


def get_net_revenue(db: Session, period: str) -> float:
    """Net Revenue = Gross Revenue - Refunds."""
    return _round2(get_revenue(db, period) - get_refunds(db, period))


def get_cogs(db: Session, period: str) -> float:
    """
    COGS = sum of the 'cost' field on sale transactions.
    This is the direct cost of items sold (not supplier purchases).
    """
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    sales_df = df[df["transaction_type"] == "sale"]
    return _round2(sales_df["cost"].fillna(0).sum())


def get_expenses(db: Session, period: str) -> float:
    """
    Total operating expenses = purchases + expense type + fees.
    Does NOT include COGS (handled separately).
    """
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    expense_types = ["purchase", "expense", "fee"]
    return _round2(df[df["transaction_type"].isin(expense_types)]["amount"].sum())


def get_purchases(db: Session, period: str) -> float:
    """Sum of supplier purchase transactions."""
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    return _round2(df[df["transaction_type"] == "purchase"]["amount"].sum())


def get_operating_expenses(db: Session, period: str) -> float:
    """Sum of expense-type transactions only."""
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    return _round2(df[df["transaction_type"] == "expense"]["amount"].sum())


def get_fees(db: Session, period: str) -> float:
    """Sum of fee transactions."""
    df = _load_period(db, period)
    if df.empty:
        return 0.0
    return _round2(df[df["transaction_type"] == "fee"]["amount"].sum())


def get_profit(db: Session, period: str) -> float:
    """
    Net Profit = Net Revenue - Total Cash Outflows.

    Formula: Net Revenue (sales - refunds) - (purchases + operating_expenses + fees)

    Note: Supplier 'purchase' transactions represent cash paid for inventory.
    COGS embedded in sale records represents the cost allocation per sale.
    For this P&L model we use cash-flow accounting:
      Net Profit = Net Revenue - All Cash Outflows
    This avoids double-counting inventory costs.
    """
    net_rev = get_net_revenue(db, period)
    expenses = get_expenses(db, period)  # purchases + expenses + fees
    return _round2(net_rev - expenses)


def get_gross_margin(db: Session, period: str) -> float:
    """
    Gross Margin % = (Net Revenue - COGS) / Net Revenue * 100.
    Returns 0.0 if net revenue is zero.
    """
    net_rev = get_net_revenue(db, period)
    cogs = get_cogs(db, period)
    if net_rev == 0:
        return 0.0
    return _round2((net_rev - cogs) / net_rev * 100)


def get_refund_rate(db: Session, period: str) -> float:
    """Refund Rate % = Refunds / Gross Revenue * 100."""
    revenue = get_revenue(db, period)
    refunds = get_refunds(db, period)
    if revenue == 0:
        return 0.0
    return _round2(refunds / revenue * 100)


def get_period_metrics(db: Session, period: str) -> PeriodMetrics:
    """Compute all key metrics for a period in one pass."""
    df = _load_period(db, period)

    if df.empty:
        return PeriodMetrics(period=period)

    revenue = _round2(df[df["transaction_type"] == "sale"]["amount"].sum())
    refunds = _round2(df[df["transaction_type"] == "refund"]["amount"].sum())
    net_revenue = _round2(revenue - refunds)
    cogs = _round2(df[df["transaction_type"] == "sale"]["cost"].fillna(0).sum())
    gross_profit = _round2(net_revenue - cogs)
    gross_margin_pct = _round2((gross_profit / net_revenue * 100) if net_revenue > 0 else 0.0)
    purchases = _round2(df[df["transaction_type"] == "purchase"]["amount"].sum())
    expenses = _round2(df[df["transaction_type"] == "expense"]["amount"].sum())
    fees = _round2(df[df["transaction_type"] == "fee"]["amount"].sum())
    total_costs = _round2(purchases + expenses + fees)
    # Cash-flow P&L: Net Revenue - All Cash Outflows (no double-counting of COGS)
    net_profit = _round2(net_revenue - total_costs)
    refund_rate_pct = _round2((refunds / revenue * 100) if revenue > 0 else 0.0)
    tx_count = len(df)

    return PeriodMetrics(
        period=period,
        revenue=revenue,
        refunds=refunds,
        net_revenue=net_revenue,
        cogs=cogs,
        gross_profit=gross_profit,
        gross_margin_pct=gross_margin_pct,
        purchases=purchases,
        expenses=expenses,
        fees=fees,
        total_costs=total_costs,
        net_profit=net_profit,
        refund_rate_pct=refund_rate_pct,
        transaction_count=tx_count,
    )


# ─── Period Comparison ────────────────────────────────────────────────────────

def compare_periods(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> dict[str, PeriodComparison]:
    """
    Compare all key metrics between two periods.
    Returns a dict keyed by metric name.
    """
    cur = get_period_metrics(db, current_period)
    prev = get_period_metrics(db, comparison_period)

    metrics_to_compare = {
        "revenue":          (cur.revenue,          prev.revenue),
        "net_revenue":      (cur.net_revenue,       prev.net_revenue),
        "refunds":          (cur.refunds,           prev.refunds),
        "cogs":             (cur.cogs,              prev.cogs),
        "gross_profit":     (cur.gross_profit,      prev.gross_profit),
        "gross_margin_pct": (cur.gross_margin_pct,  prev.gross_margin_pct),
        "purchases":        (cur.purchases,         prev.purchases),
        "expenses":         (cur.expenses,          prev.expenses),
        "fees":             (cur.fees,              prev.fees),
        "total_costs":      (cur.total_costs,       prev.total_costs),
        "net_profit":       (cur.net_profit,        prev.net_profit),
        "refund_rate_pct":  (cur.refund_rate_pct,   prev.refund_rate_pct),
    }

    comparisons: dict[str, PeriodComparison] = {}
    for metric, (c_val, p_val) in metrics_to_compare.items():
        change = _round2(c_val - p_val)
        comparisons[metric] = PeriodComparison(
            metric=metric,
            current_period=current_period,
            comparison_period=comparison_period,
            current_value=c_val,
            comparison_value=p_val,
            change=change,
            change_pct=_safe_pct_change(c_val, p_val),
            direction=_direction(change),
        )
    return comparisons


# ─── Category Analysis ────────────────────────────────────────────────────────

def analyze_categories(db: Session, period: str) -> list[CategoryMetrics]:
    """Return revenue, COGS, and gross margin by category for the period."""
    df = _load_period(db, period)
    if df.empty:
        return []

    results: list[CategoryMetrics] = []
    categories = df["category"].dropna().unique()

    for cat in categories:
        cat_df = df[df["category"] == cat]
        sales_df = cat_df[cat_df["transaction_type"] == "sale"]
        refund_df = cat_df[cat_df["transaction_type"] == "refund"]

        revenue = _round2(sales_df["amount"].sum())
        cogs = _round2(sales_df["cost"].fillna(0).sum())
        refunds = _round2(refund_df["amount"].sum())
        net_rev = _round2(revenue - refunds)
        gross_profit = _round2(net_rev - cogs)
        margin = _round2((gross_profit / net_rev * 100) if net_rev > 0 else 0.0)

        results.append(CategoryMetrics(
            period=period,
            category=cat,
            revenue=revenue,
            cogs=cogs,
            gross_profit=gross_profit,
            gross_margin_pct=margin,
            refunds=refunds,
            transaction_count=len(cat_df),
        ))

    return sorted(results, key=lambda x: x.revenue, reverse=True)


def compare_categories(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[dict[str, Any]]:
    """Compare category performance between two periods."""
    cur_cats = {c.category: c for c in analyze_categories(db, current_period)}
    prev_cats = {c.category: c for c in analyze_categories(db, comparison_period)}

    all_cats = set(cur_cats.keys()) | set(prev_cats.keys())
    results = []

    for cat in all_cats:
        cur = cur_cats.get(cat)
        prev = prev_cats.get(cat)
        cur_margin = cur.gross_margin_pct if cur else 0.0
        prev_margin = prev.gross_margin_pct if prev else 0.0
        cur_rev = cur.revenue if cur else 0.0
        prev_rev = prev.revenue if prev else 0.0
        cur_gp = cur.gross_profit if cur else 0.0
        prev_gp = prev.gross_profit if prev else 0.0

        results.append({
            "category": cat,
            "current_revenue": cur_rev,
            "comparison_revenue": prev_rev,
            "revenue_change": _round2(cur_rev - prev_rev),
            "current_gross_profit": cur_gp,
            "comparison_gross_profit": prev_gp,
            "gross_profit_change": _round2(cur_gp - prev_gp),
            "current_margin_pct": cur_margin,
            "comparison_margin_pct": prev_margin,
            "margin_change_ppt": _round2(cur_margin - prev_margin),
        })

    return sorted(results, key=lambda x: abs(x["gross_profit_change"]), reverse=True)


# ─── Product Analysis ─────────────────────────────────────────────────────────

def analyze_products(db: Session, period: str) -> list[ProductMetrics]:
    """Return margin metrics per product."""
    df = _load_period(db, period)
    if df.empty:
        return []

    sales_df = df[df["transaction_type"] == "sale"]
    if sales_df.empty:
        return []

    results: list[ProductMetrics] = []
    for product in sales_df["product"].dropna().unique():
        p_df = sales_df[sales_df["product"] == product]
        revenue = _round2(p_df["amount"].sum())
        cogs = _round2(p_df["cost"].fillna(0).sum())
        gross_profit = _round2(revenue - cogs)
        margin = _round2((gross_profit / revenue * 100) if revenue > 0 else 0.0)
        quantity = _round2(p_df["quantity"].fillna(1).sum())
        category = p_df["category"].iloc[0] if not p_df.empty else ""

        results.append(ProductMetrics(
            period=period,
            product=product,
            category=category,
            revenue=revenue,
            cogs=cogs,
            gross_profit=gross_profit,
            gross_margin_pct=margin,
            quantity=quantity,
            unit_count=len(p_df),
        ))

    return sorted(results, key=lambda x: x.revenue, reverse=True)


def compare_products(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[dict[str, Any]]:
    """Compare product margins between two periods."""
    cur_prods = {p.product: p for p in analyze_products(db, current_period)}
    prev_prods = {p.product: p for p in analyze_products(db, comparison_period)}

    all_prods = set(cur_prods.keys()) | set(prev_prods.keys())
    results = []

    for prod in all_prods:
        cur = cur_prods.get(prod)
        prev = prev_prods.get(prod)
        cur_gp = cur.gross_profit if cur else 0.0
        prev_gp = prev.gross_profit if prev else 0.0
        cur_margin = cur.gross_margin_pct if cur else 0.0
        prev_margin = prev.gross_margin_pct if prev else 0.0
        gp_change = _round2(cur_gp - prev_gp)

        results.append({
            "product": prod,
            "category": (cur or prev).category,
            "current_gross_profit": cur_gp,
            "comparison_gross_profit": prev_gp,
            "gross_profit_change": gp_change,
            "current_margin_pct": cur_margin,
            "comparison_margin_pct": prev_margin,
            "margin_change_ppt": _round2(cur_margin - prev_margin),
        })

    return sorted(results, key=lambda x: abs(x["gross_profit_change"]), reverse=True)


# ─── Supplier Analysis ────────────────────────────────────────────────────────

def analyze_suppliers(db: Session, period: str) -> list[SupplierMetrics]:
    """Return total cost per supplier for the period."""
    df = _load_period(db, period)
    if df.empty:
        return []

    purchase_df = df[df["transaction_type"] == "purchase"]
    if purchase_df.empty:
        return []

    results: list[SupplierMetrics] = []
    for supplier in purchase_df["supplier"].dropna().unique():
        s_df = purchase_df[purchase_df["supplier"] == supplier]
        total_cost = _round2(s_df["amount"].sum())
        categories = list(s_df["category"].dropna().unique())

        results.append(SupplierMetrics(
            period=period,
            supplier=supplier,
            total_cost=total_cost,
            transaction_count=len(s_df),
            categories=categories,
        ))

    return sorted(results, key=lambda x: x.total_cost, reverse=True)


def compare_suppliers(
    db: Session,
    current_period: str,
    comparison_period: str,
) -> list[dict[str, Any]]:
    """Compare supplier costs between two periods."""
    cur_sups = {s.supplier: s for s in analyze_suppliers(db, current_period)}
    prev_sups = {s.supplier: s for s in analyze_suppliers(db, comparison_period)}

    all_sups = set(cur_sups.keys()) | set(prev_sups.keys())
    results = []

    for sup in all_sups:
        cur = cur_sups.get(sup)
        prev = prev_sups.get(sup)
        cur_cost = cur.total_cost if cur else 0.0
        prev_cost = prev.total_cost if prev else 0.0
        change = _round2(cur_cost - prev_cost)

        results.append({
            "supplier": sup,
            "current_cost": cur_cost,
            "comparison_cost": prev_cost,
            "cost_change": change,
            "cost_change_pct": _safe_pct_change(cur_cost, prev_cost),
            "direction": _direction(change),
            "current_tx_count": cur.transaction_count if cur else 0,
            "comparison_tx_count": prev.transaction_count if prev else 0,
        })

    return sorted(results, key=lambda x: abs(x["cost_change"]), reverse=True)


# ─── Supporting Evidence Retrieval ───────────────────────────────────────────

def get_supporting_transactions(
    db: Session,
    period: str,
    transaction_type: str | None = None,
    supplier: str | None = None,
    product: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Retrieve transactions matching the given filters.
    Used to provide evidence for investigation findings.
    """
    df = _load_period(db, period)
    if df.empty:
        return []

    if transaction_type:
        df = df[df["transaction_type"] == transaction_type]
    if supplier:
        df = df[df["supplier"] == supplier]
    if product:
        df = df[df["product"] == product]
    if category:
        df = df[df["category"] == category]

    df = df.sort_values("amount", ascending=False).head(limit)

    return df.to_dict(orient="records")


def get_available_periods(db: Session) -> list[str]:
    """Return all distinct periods in the transaction table, sorted."""
    rows = db.query(Transaction.period).distinct().all()
    return sorted([r[0] for r in rows])
