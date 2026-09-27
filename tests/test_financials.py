"""Tests for the deterministic financial engine."""
import pytest
from app.services.financial_engine import (
    get_revenue, get_refunds, get_net_revenue, get_cogs,
    get_expenses, get_profit, get_gross_margin, get_refund_rate,
    get_period_metrics, compare_periods,
    analyze_categories, analyze_products, analyze_suppliers,
    compare_suppliers,
)


class TestBasicMetrics:

    def test_revenue_january(self, seeded_db):
        revenue = get_revenue(seeded_db, "2026-01")
        assert revenue > 0, "January should have positive revenue"
        # Seed generates approximately $57,930 in sales
        assert 40_000 <= revenue <= 80_000

    def test_revenue_february_greater_than_january(self, seeded_db):
        jan = get_revenue(seeded_db, "2026-01")
        feb = get_revenue(seeded_db, "2026-02")
        assert feb > jan, "February revenue should exceed January (by design)"

    def test_refunds_february_greater_than_january(self, seeded_db):
        jan_ref = get_refunds(seeded_db, "2026-01")
        feb_ref = get_refunds(seeded_db, "2026-02")
        assert feb_ref > jan_ref, "February refunds should exceed January (by design)"
        # Designed: Jan $2,000 → Feb $6,200
        assert abs(jan_ref - 2000) < 50
        assert abs(feb_ref - 6200) < 100

    def test_net_revenue_equals_revenue_minus_refunds(self, seeded_db):
        revenue = get_revenue(seeded_db, "2026-01")
        refunds = get_refunds(seeded_db, "2026-01")
        net = get_net_revenue(seeded_db, "2026-01")
        assert abs(net - (revenue - refunds)) < 0.01

    def test_profit_formula_consistency(self, seeded_db):
        """Net Profit = Net Revenue - Total Expenses."""
        net_rev = get_net_revenue(seeded_db, "2026-01")
        expenses = get_expenses(seeded_db, "2026-01")
        profit = get_profit(seeded_db, "2026-01")
        assert abs(profit - (net_rev - expenses)) < 0.01

    def test_profit_decreases_february(self, seeded_db):
        jan_profit = get_profit(seeded_db, "2026-01")
        feb_profit = get_profit(seeded_db, "2026-02")
        assert feb_profit < jan_profit, "Profit should decrease in February (by design)"

    def test_gross_margin_returns_percentage(self, seeded_db):
        margin = get_gross_margin(seeded_db, "2026-01")
        assert 0 <= margin <= 100, "Gross margin must be a percentage between 0 and 100"

    def test_refund_rate_formula(self, seeded_db):
        revenue = get_revenue(seeded_db, "2026-01")
        refunds = get_refunds(seeded_db, "2026-01")
        rate = get_refund_rate(seeded_db, "2026-01")
        expected = round(refunds / revenue * 100, 2)
        assert abs(rate - expected) < 0.01

    def test_zero_revenue_period(self, db):
        """Edge case: period with no data should return zeros."""
        assert get_revenue(db, "2000-01") == 0.0
        assert get_profit(db, "2000-01") == 0.0
        assert get_gross_margin(db, "2000-01") == 0.0
        assert get_refund_rate(db, "2000-01") == 0.0


class TestPeriodMetrics:

    def test_metrics_internally_consistent(self, seeded_db):
        m = get_period_metrics(seeded_db, "2026-02")
        # Net revenue check
        assert abs(m.net_revenue - (m.revenue - m.refunds)) < 0.01
        # Total costs
        assert abs(m.total_costs - (m.purchases + m.expenses + m.fees)) < 0.01
        # Profit
        assert abs(m.net_profit - (m.net_revenue - m.total_costs)) < 0.01

    def test_empty_period_metrics(self, db):
        m = get_period_metrics(db, "1900-01")
        assert m.revenue == 0.0
        assert m.net_profit == 0.0
        assert m.transaction_count == 0


class TestPeriodComparison:

    def test_compare_periods_returns_all_metrics(self, seeded_db):
        comps = compare_periods(seeded_db, "2026-02", "2026-01")
        required = {"revenue", "net_revenue", "refunds", "net_profit", "total_costs"}
        assert required.issubset(set(comps.keys()))

    def test_profit_comparison_direction(self, seeded_db):
        comps = compare_periods(seeded_db, "2026-02", "2026-01")
        profit_cmp = comps["net_profit"]
        assert profit_cmp.direction == "decrease", "Profit should decrease Feb vs Jan"
        assert profit_cmp.change < 0

    def test_same_period_comparison(self, seeded_db):
        comps = compare_periods(seeded_db, "2026-01", "2026-01")
        assert comps["net_profit"].change == 0.0

    def test_refund_increase_detected(self, seeded_db):
        comps = compare_periods(seeded_db, "2026-02", "2026-01")
        ref_cmp = comps["refunds"]
        assert ref_cmp.direction == "increase"
        # Designed: +$4,200
        assert ref_cmp.change > 3000


class TestSupplierAnalysis:

    def test_supplier_a_increase_detected(self, seeded_db):
        """Supplier A costs should increase from Jan to Feb."""
        sups = compare_suppliers(seeded_db, "2026-02", "2026-01")
        sup_a = next((s for s in sups if s["supplier"] == "Supplier A"), None)
        assert sup_a is not None, "Supplier A should be in results"
        assert sup_a["cost_change"] > 0, "Supplier A cost should increase"
        # Designed: +$6,100
        assert abs(sup_a["cost_change"] - 6100) < 200

    def test_supplier_b_increase_detected(self, seeded_db):
        sups = compare_suppliers(seeded_db, "2026-02", "2026-01")
        sup_b = next((s for s in sups if s["supplier"] == "Supplier B"), None)
        assert sup_b is not None
        assert sup_b["cost_change"] > 0
        # Designed: +$3,500
        assert abs(sup_b["cost_change"] - 3500) < 200

    def test_supplier_january_costs(self, seeded_db):
        sups = analyze_suppliers(seeded_db, "2026-01")
        sup_a = next((s for s in sups if s.supplier == "Supplier A"), None)
        assert sup_a is not None
        assert abs(sup_a.total_cost - 12000) < 200


class TestCategoryAnalysis:

    def test_categories_returned(self, seeded_db):
        cats = analyze_categories(seeded_db, "2026-01")
        assert len(cats) > 0
        cat_names = [c.category for c in cats]
        assert "Electronics" in cat_names

    def test_margin_is_percentage(self, seeded_db):
        cats = analyze_categories(seeded_db, "2026-01")
        for c in cats:
            if c.revenue > 0:
                assert 0 <= c.gross_margin_pct <= 100


class TestProductAnalysis:

    def test_products_returned(self, seeded_db):
        prods = analyze_products(seeded_db, "2026-01")
        assert len(prods) > 0

    def test_product_margin_consistency(self, seeded_db):
        prods = analyze_products(seeded_db, "2026-01")
        for p in prods:
            if p.revenue > 0:
                expected_margin = round((p.gross_profit / p.revenue) * 100, 2)
                assert abs(p.gross_margin_pct - expected_margin) < 0.1
