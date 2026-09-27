"""Tests for the FastAPI routes."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(seeded_session_factory):
    """FastAPI test client with seeded database."""
    from app.main import app
    from app.database import get_db

    def override_db():
        session = seeded_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestHealthEndpoint:

    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestDashboardEndpoint:

    def test_dashboard_returns_200(self, client):
        r = client.get("/api/dashboard?period=2026-02")
        assert r.status_code == 200

    def test_dashboard_has_metrics(self, client):
        r = client.get("/api/dashboard?period=2026-02")
        data = r.json()
        assert "metrics" in data
        assert data["metrics"]["revenue"] > 0

    def test_dashboard_invalid_period(self, client):
        r = client.get("/api/dashboard?period=invalid")
        assert r.status_code == 422


class TestTransactionEndpoints:

    def test_list_transactions(self, client):
        r = client.get("/api/transactions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0

    def test_filter_by_period(self, client):
        r = client.get("/api/transactions?period=2026-01")
        assert r.status_code == 200
        data = r.json()
        assert all(tx["period"] == "2026-01" for tx in data)

    def test_filter_by_type(self, client):
        r = client.get("/api/transactions?transaction_type=sale")
        assert r.status_code == 200
        data = r.json()
        assert all(tx["transaction_type"] == "sale" for tx in data)

    def test_get_nonexistent_transaction(self, client):
        r = client.get("/api/transactions/TX-NOTEXIST")
        assert r.status_code == 404

    def test_upload_invalid_file_type(self, client):
        r = client.post(
            "/api/transactions/upload",
            files={"file": ("test.txt", b"not csv", "text/plain")},
        )
        assert r.status_code == 400

    def test_upload_missing_columns(self, client):
        csv_data = b"col1,col2\nval1,val2\n"
        r = client.post(
            "/api/transactions/upload",
            files={"file": ("test.csv", csv_data, "text/csv")},
        )
        assert r.status_code == 400


class TestInvestigationEndpoints:

    def test_investigate_returns_result(self, client):
        r = client.post("/api/investigate", json={
            "question": "Why did profit decrease?",
            "current_period": "2026-02",
            "comparison_period": "2026-01",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["investigation_id"].startswith("INV-")

    def test_investigate_same_period_rejected(self, client):
        r = client.post("/api/investigate", json={
            "question": "What changed?",
            "current_period": "2026-01",
            "comparison_period": "2026-01",
        })
        assert r.status_code == 400

    def test_investigate_invalid_period_rejected(self, client):
        r = client.post("/api/investigate", json={
            "question": "What changed?",
            "current_period": "not-a-period",
            "comparison_period": "2026-01",
        })
        assert r.status_code == 422

    def test_investigate_short_question_rejected(self, client):
        r = client.post("/api/investigate", json={
            "question": "hi",
            "current_period": "2026-02",
            "comparison_period": "2026-01",
        })
        assert r.status_code == 422

    def test_get_investigation_not_found(self, client):
        r = client.get("/api/investigations/INV-NOTEXIST")
        assert r.status_code == 404

    def test_list_investigations(self, client):
        r = client.get("/api/investigations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
