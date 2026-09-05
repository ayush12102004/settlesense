"""Integration tests for SettleSense API endpoints."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import json
import pytest
from api import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_dashboard_endpoint(client):
    """Verify that /api/dashboard returns complete bundle with model metadata."""
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.get_json()
    assert "summary" in data
    assert "cash_position" in data
    assert "tax_reconciliation" in data
    assert "model_info" in data


def test_tax_reconciliation_endpoint(client):
    """Verify that /api/tax-reconciliation returns valid ITC status."""
    res = client.get("/api/tax-reconciliation")
    assert res.status_code == 200
    data = res.get_json()
    assert data["tax_status"] == "MATCHED_ITC_ELIGIBLE"
    assert data["sac_code"] == "997159"


def test_cash_simulation_endpoint(client):
    """Verify cash position delay scenario simulation."""
    res = client.post("/api/cash-position/simulate", json={"lag_days": 2})
    assert res.status_code == 200
    data = res.get_json()
    assert data["simulated_lag_days"] == 2
    assert "daily_projection" in data


def test_chat_endpoint(client):
    """Verify conversational Q&A agent response."""
    res = client.post("/api/chat", json={"message": "Summarize exceptions", "history": []})
    assert res.status_code == 200
    data = res.get_json()
    assert "response" in data
    assert len(data["response"]) > 20


def test_tax_report_download_endpoint(client):
    """Verify that /api/tax/report returns attachment header and valid JSON."""
    res = client.get("/api/tax/report")
    assert res.status_code == 200
    assert "attachment" in res.headers.get("Content-Disposition", "")
    data = res.get_json()
    assert "reconciliation" in data
