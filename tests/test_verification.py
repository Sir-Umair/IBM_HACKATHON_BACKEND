"""Tests for the verification node."""
import pytest
from app.agent.nodes.verification import (
    _check, _verify_pct_consistent, TOLERANCE, PCT_TOLERANCE
)
from app.agent.state import initial_state


class TestVerificationChecks:

    def test_check_passes_exact_match(self):
        c = _check("test", 100.0, 100.0)
        assert c["passed"] is True

    def test_check_passes_within_tolerance(self):
        c = _check("test", 100.0, 100.04)
        assert c["passed"] is True

    def test_check_fails_outside_tolerance(self):
        c = _check("test", 100.0, 101.0)
        assert c["passed"] is False
        assert "MISMATCH" in c["message"]

    def test_check_negative_values(self):
        c = _check("neg test", -50.0, -50.0)
        assert c["passed"] is True

    def test_check_zero_values(self):
        c = _check("zero test", 0.0, 0.0)
        assert c["passed"] is True


class TestPercentageVerification:

    def test_pct_consistent_with_correct_data(self):
        finding = {
            "entity": "TestEntity",
            "baseline": 10000.0,
            "current_value": 18100.0,
            "difference_pct": 81.0,
        }
        check = _verify_pct_consistent(finding)
        assert check["passed"] is True  # 81% is correct for 10000→18100

    def test_pct_detects_inconsistency(self):
        finding = {
            "entity": "TestEntity",
            "baseline": 10000.0,
            "current_value": 18100.0,
            "difference_pct": 50.0,  # Wrong — should be ~81%
        }
        check = _verify_pct_consistent(finding)
        assert check["passed"] is False

    def test_pct_zero_baseline(self):
        finding = {
            "entity": "TestEntity",
            "baseline": 0.0,
            "current_value": 5000.0,
            "difference_pct": 0.0,
        }
        check = _verify_pct_consistent(finding)
        # 0 baseline → pct_change = 0 → should pass (both 0)
        assert check["passed"] is True


class TestVerificationNode:

    def test_verification_runs_without_error(self, seeded_db):
        """Full verification node should execute without exception."""
        from app.agent.nodes.verification import verification_node
        state = initial_state(
            question="test",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-VERIFY",
        )
        state["current_metrics"] = {"revenue": 63438.0, "net_profit": -8362.0, "cogs": 0.0}
        state["anomalies"] = []
        state["evidence"] = []

        result = verification_node(state, seeded_db)
        assert result["verification_status"] in ("passed", "partial", "failed")

    def test_verification_with_findings(self, seeded_db):
        """Verification with real findings should pass for correct data."""
        from app.agent.graph import build_investigation_graph
        state = initial_state(
            question="Why did expenses increase?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-VERIFY-2",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)
        assert result["verification_status"] in ("passed", "partial")
        assert result["status"] == "completed"
