"""Dashboard routes — summary metrics and chart data."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_models import DashboardResponse, PeriodMetrics as PeriodMetricsSchema
from app.services.financial_engine import (
    get_period_metrics,
    get_available_periods,
    analyze_categories,
    _load_period,
    _round2,
)

router = APIRouter(prefix="/api", tags=["dashboard"])


def _to_schema(m) -> PeriodMetricsSchema:
    return PeriodMetricsSchema(
        period=m.period,
        revenue=m.revenue,
        expenses=m.total_costs,
        cogs=m.cogs,
        profit=m.net_profit,
        gross_margin_pct=m.gross_margin_pct,
        refund_rate_pct=m.refund_rate_pct,
        transaction_count=m.transaction_count,
    )


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "AI Financial Investigator"}


@router.api_route("/seed", methods=["GET", "POST"])
def seed_database():
    """Seed the database with deterministic demo data (900+ transactions across 3 months)."""
    try:
        import seed_data
        seed_data.seed_all()
        return {"status": "ok", "message": "Successfully seeded demo financial transactions"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    """Return dashboard summary for the given period."""
    available = get_available_periods(db)
    if not available:
        active_p = period or "2026-02"
        return DashboardResponse(
            current_period=active_p,
            metrics=PeriodMetricsSchema(
                period=active_p, revenue=0, expenses=0, cogs=0,
                profit=0, gross_margin_pct=0, refund_rate_pct=0, transaction_count=0,
            ),
            available_periods=[],
            daily_trend=[],
            cumulative_trend=[],
            revenue_vs_expenses=[],
            profit_trend=[],
            expense_breakdown=[],
            category_performance=[],
        )

    # Auto-select the latest period containing data if not specified or invalid
    if not period or period not in available:
        period = available[-1]

    # Current and prior period
    cur = get_period_metrics(db, period)

    prior_period = None
    if len(available) >= 2:
        idx = available.index(period) if period in available else -1
        if idx > 0:
            prior_period = available[idx - 1]
    prior = get_period_metrics(db, prior_period) if prior_period else None

    # Revenue vs Expenses trend
    trend_data = []
    for p in available:
        m = get_period_metrics(db, p)
        trend_data.append({
            "period": p,
            "revenue": m.net_revenue,
            "expenses": m.total_costs,
            "profit": m.net_profit,
        })

    # Daily trend and cumulative trajectory for the selected period
    df = _load_period(db, period)
    daily_trend: list[dict[str, Any]] = []
    cumulative_trend: list[dict[str, Any]] = []
    expense_breakdown: list[dict[str, Any]] = []

    if not df.empty:
        # Expense breakdown (purchases/expenses/fees)
        for tx_type, label in [("purchase", "Purchases"), ("expense", "Operating"), ("fee", "Fees")]:
            amt = _round2(float(df[df["transaction_type"] == tx_type]["amount"].sum()))
            if amt > 0:
                expense_breakdown.append({"name": label, "value": amt})

        # Daily timeline
        dates = sorted(df["date"].unique())
        cum_rev = 0.0
        cum_exp = 0.0
        cum_prof = 0.0

        for d in dates:
            d_str = str(d)
            sub = df[df["date"] == d]
            sales = float(sub[sub["transaction_type"] == "sale"]["amount"].sum())
            refunds = float(sub[sub["transaction_type"] == "refund"]["amount"].sum())
            day_rev = _round2(sales - refunds)
            day_exp = _round2(float(sub[sub["transaction_type"].isin(["purchase", "expense", "fee"])]["amount"].sum()))
            day_cogs = _round2(float(sub[sub["transaction_type"] == "sale"]["cost"].sum()))
            day_prof = _round2(day_rev - day_cogs - day_exp)

            cum_rev = _round2(cum_rev + day_rev)
            cum_exp = _round2(cum_exp + day_exp)
            cum_prof = _round2(cum_prof + day_prof)

            daily_trend.append({
                "date": d_str,
                "revenue": day_rev,
                "expenses": day_exp,
                "profit": day_prof,
                "transaction_count": len(sub),
            })
            cumulative_trend.append({
                "date": d_str,
                "revenue": cum_rev,
                "expenses": cum_exp,
                "profit": cum_prof,
            })

    # Category performance
    cat_metrics = analyze_categories(db, period)
    cat_performance = [
        {
            "category": c.category,
            "revenue": c.revenue,
            "gross_profit": c.gross_profit,
            "margin_pct": c.gross_margin_pct,
        }
        for c in cat_metrics
    ]

    return DashboardResponse(
        current_period=period,
        metrics=_to_schema(cur),
        prior_metrics=_to_schema(prior) if prior else None,
        revenue_vs_expenses=trend_data,
        daily_trend=daily_trend,
        cumulative_trend=cumulative_trend,
        profit_trend=trend_data,
        expense_breakdown=expense_breakdown,
        category_performance=cat_performance,
        available_periods=available,
    )



@router.get("/metrics")
def get_metrics(
    period: str = Query(default="2026-02", pattern=r"^\d{4}-\d{2}$"),
    comparison: str = Query(default="2026-01", pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
):
    """Return period metrics and comparison."""
    from app.services.financial_engine import compare_periods
    cur = get_period_metrics(db, period)
    cmp = compare_periods(db, period, comparison)
    return {
        "current": _to_schema(cur),
        "comparison": {k: {
            "change": v.change,
            "change_pct": v.change_pct,
            "direction": v.direction,
            "current_value": v.current_value,
            "comparison_value": v.comparison_value,
        } for k, v in cmp.items()},
    }


@router.get("/categories")
def get_categories(
    period: str = Query(default="2026-02", pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
):
    cats = analyze_categories(db, period)
    return [
        {
            "period": c.period,
            "category": c.category,
            "revenue": c.revenue,
            "cogs": c.cogs,
            "gross_profit": c.gross_profit,
            "gross_margin_pct": c.gross_margin_pct,
            "refunds": c.refunds,
            "transaction_count": c.transaction_count,
        }
        for c in cats
    ]


@router.get("/products")
def get_products(
    period: str = Query(default="2026-02", pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
):
    from app.services.financial_engine import analyze_products
    prods = analyze_products(db, period)
    return [
        {
            "period": p.period,
            "product": p.product,
            "category": p.category,
            "revenue": p.revenue,
            "cogs": p.cogs,
            "gross_profit": p.gross_profit,
            "gross_margin_pct": p.gross_margin_pct,
            "quantity": p.quantity,
        }
        for p in prods
    ]


@router.get("/suppliers")
def get_suppliers(
    period: str = Query(default="2026-02", pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
):
    from app.services.financial_engine import analyze_suppliers
    sups = analyze_suppliers(db, period)
    return [
        {
            "period": s.period,
            "supplier": s.supplier,
            "total_cost": s.total_cost,
            "transaction_count": s.transaction_count,
            "categories": s.categories,
        }
        for s in sups
    ]
