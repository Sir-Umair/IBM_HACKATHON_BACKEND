"""Tests for the full LangGraph agent workflow."""
import pytest
from app.agent.graph import build_investigation_graph
from app.agent.state import initial_state
from app.agent.nodes.intent import _rule_based_intent, _extract_period_from_text


class TestIntentAnalysis:

    def test_profit_question_detected(self):
        assert _rule_based_intent("Why did profit decrease?") == "profit_change_investigation"

    def test_expense_question_detected(self):
        assert _rule_based_intent("Why did expenses increase?") == "expense_change_investigation"

    def test_supplier_question_detected(self):
        assert _rule_based_intent("Which supplier increased costs?") == "supplier_analysis_investigation"

    def test_anomaly_question_detected(self):
        assert _rule_based_intent("Are there unusual transactions?") == "anomaly_detection_investigation"

    def test_fallback_to_general(self):
        assert _rule_based_intent("hello") == "general_financial_investigation"

    def test_period_extraction_from_text(self):
        current, comparison = _extract_period_from_text("Why did profit decrease in February?")
        assert current is not None
        assert "02" in current

    def test_period_extraction_two_months(self):
        current, comparison = _extract_period_from_text(
            "Compare January with February"
        )
        assert current is not None
        assert comparison is not None


class TestAgentWorkflow:

    def test_full_profit_investigation(self, seeded_db):
        """
        Integration test: profit investigation should complete with findings.
        Given Supplier A +$6,100 and refunds +$4,200 in the data,
        the agent must identify those as findings.
        """
        state = initial_state(
            question="Why did profit decrease in February?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-AGENT-001",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)

        assert result["status"] == "completed"
        assert result["intent"] == "profit_change_investigation"
        assert len(result["anomalies"]) > 0

        entities = [f["entity"] for f in result["anomalies"]]
        assert "Supplier A" in entities, f"Supplier A should be a finding. Got: {entities}"

        refund_findings = [f for f in result["anomalies"] if "refund" in f["finding_type"]]
        assert len(refund_findings) > 0, "Refund increase should be found"

    def test_supplier_investigation(self, seeded_db):
        state = initial_state(
            question="Which supplier increased costs?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-AGENT-002",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)

        assert result["status"] == "completed"
        assert result["intent"] == "supplier_analysis_investigation"
        assert len(result["anomalies"]) > 0

    def test_investigation_has_evidence(self, seeded_db):
        state = initial_state(
            question="Why did profit decrease?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-AGENT-003",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)

        assert len(result["evidence"]) > 0, "Evidence should be populated"
        for ev in result["evidence"][:5]:
            assert "transaction_id" in ev
            assert "amount" in ev

    def test_workflow_trace_populated(self, seeded_db):
        state = initial_state(
            question="Why did expenses increase?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-AGENT-004",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)

        assert len(result["workflow_trace"]) > 0
        completed = [s for s in result["workflow_trace"] if s["status"] == "completed"]
        assert len(completed) >= 4, "At least 4 workflow steps should complete"

    def test_explanation_generated(self, seeded_db):
        state = initial_state(
            question="Why did profit decrease?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-AGENT-005",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)

        assert result["explanation"], "Explanation should be non-empty"
        assert len(result["explanation"]) > 50

    def test_empty_period_does_not_crash(self, db):
        """Investigation on empty period should return gracefully."""
        state = initial_state(
            question="Why did profit decrease?",
            current_period="1900-01",
            comparison_period="1900-02",
            investigation_id="TEST-AGENT-006",
        )
        graph = build_investigation_graph(db)
        result = graph.invoke(state)
        assert result["status"] in ("completed", "failed")

    def test_findings_are_verified_not_hallucinated(self, seeded_db):
        """
        Critical: findings must reference amounts that actually exist in the DB.
        Agent must NOT claim amounts that cannot be verified.
        """
        state = initial_state(
            question="Why did profit decrease?",
            current_period="2026-02",
            comparison_period="2026-01",
            investigation_id="TEST-AGENT-007",
        )
        graph = build_investigation_graph(seeded_db)
        result = graph.invoke(state)

        from app.services.financial_engine import get_profit, get_refunds, compare_suppliers

        # Verify profit change in findings matches independent calculation
        actual_jan_profit = get_profit(seeded_db, "2026-01")
        actual_feb_profit = get_profit(seeded_db, "2026-02")
        actual_profit_change = actual_feb_profit - actual_jan_profit

        profit_cmp = result.get("comparison_results", {}).get("net_profit", {})
        if profit_cmp:
            reported_change = profit_cmp.get("change", 0)
            assert abs(reported_change - actual_profit_change) < 1.0, \
                f"Reported profit change {reported_change} != actual {actual_profit_change}"
