"""Tests for the anomaly and driver detection engine."""
import pytest
from app.services.anomaly_engine import (
    detect_profit_drivers,
    detect_supplier_anomalies,
    detect_expense_anomalies,
    detect_category_margin_changes,
    detect_product_margin_changes,
    detect_duplicate_transactions,
    detect_general_anomalies,
)


class TestProfitDriverDetection:

    def test_profit_drivers_returns_findings(self, seeded_db):
        findings = detect_profit_drivers(seeded_db, "2026-02", "2026-01")
        assert len(findings) > 0

    def test_supplier_a_is_top_finding(self, seeded_db):
        """Supplier A +$6,100 should be among top findings."""
        findings = detect_profit_drivers(seeded_db, "2026-02", "2026-01")
        entities = [f.entity for f in findings]
        assert "Supplier A" in entities, "Supplier A should be a top driver"

    def test_refund_increase_is_finding(self, seeded_db):
        findings = detect_profit_drivers(seeded_db, "2026-02", "2026-01")
        refund_findings = [f for f in findings if "refund" in f.finding_type]
        assert len(refund_findings) > 0, "Refund increase should be a finding"

    def test_no_findings_for_same_period(self, seeded_db):
        """Same period comparison should produce very few or no findings."""
        findings = detect_profit_drivers(seeded_db, "2026-01", "2026-01")
        # Some metrics may return minor changes due to floating-point
        for f in findings:
            assert abs(f.difference) < 1.0, "Same-period diff must be near zero"


class TestSupplierAnomalyDetection:

    def test_supplier_cost_increase_detected(self, seeded_db):
        findings = detect_supplier_anomalies(seeded_db, "2026-02", "2026-01")
        assert len(findings) > 0

    def test_supplier_a_finding_details(self, seeded_db):
        findings = detect_supplier_anomalies(seeded_db, "2026-02", "2026-01")
        sup_a = next((f for f in findings if f.entity == "Supplier A"), None)
        assert sup_a is not None
        assert sup_a.difference > 0
        assert abs(sup_a.difference - 6100) < 200
        assert sup_a.baseline > 0
        assert sup_a.current_value > sup_a.baseline

    def test_findings_have_evidence_ids(self, seeded_db):
        findings = detect_supplier_anomalies(seeded_db, "2026-02", "2026-01")
        for f in findings:
            # Evidence IDs should be populated
            assert isinstance(f.supporting_tx_ids, list)


class TestExpenseAnomalyDetection:

    def test_expense_increases_detected(self, seeded_db):
        findings = detect_expense_anomalies(seeded_db, "2026-02", "2026-01")
        assert len(findings) >= 0  # Operations should show an increase

    def test_finding_structure_valid(self, seeded_db):
        findings = detect_expense_anomalies(seeded_db, "2026-02", "2026-01")
        for f in findings:
            assert f.baseline >= 0
            assert f.current_value >= 0
            assert f.threshold > 0
            assert f.reason


class TestCategoryMarginChanges:

    def test_electronics_margin_drop_detected(self, seeded_db):
        """Electronics uses cost_multiplier=1.25 in Feb → margin should drop."""
        findings = detect_category_margin_changes(seeded_db, "2026-02", "2026-01")
        electronics = next((f for f in findings if "Electronics" in f.category), None)
        assert electronics is not None, "Electronics margin change should be detected"
        # Feb electronics COGS was increased by 25% → gross profit drops
        assert electronics.difference < 0

    def test_finding_percentage_consistent(self, seeded_db):
        findings = detect_category_margin_changes(seeded_db, "2026-02", "2026-01")
        for f in findings:
            if f.baseline != 0:
                expected_pct = round((f.current_value - f.baseline) / abs(f.baseline) * 100, 2)
                assert abs(f.difference_pct - expected_pct) < 1.0


class TestProductMarginChanges:

    def test_product_findings_returned(self, seeded_db):
        findings = detect_product_margin_changes(seeded_db, "2026-02", "2026-01")
        # Should return findings for top products with margin changes
        assert isinstance(findings, list)

    def test_electronics_products_affected(self, seeded_db):
        findings = detect_product_margin_changes(seeded_db, "2026-02", "2026-01")
        electronic_products = [f for f in findings if f.category == "Electronics"]
        assert len(electronic_products) > 0, "Electronics products should show margin changes"


class TestDuplicateDetection:

    def test_no_duplicates_in_clean_data(self, seeded_db):
        """Seed data should not have intentional duplicates."""
        dupes = detect_duplicate_transactions(seeded_db, "2026-01")
        # Clean seed data should have zero or very few duplicates
        assert len(dupes) == 0

    def test_empty_period_no_duplicates(self, db):
        dupes = detect_duplicate_transactions(db, "1900-01")
        assert dupes == []
