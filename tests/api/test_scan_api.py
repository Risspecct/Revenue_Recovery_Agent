from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import recovery
from app.main import app
from app.services.revenue_scanner import RevenueScanResult


def test_scan_endpoint_returns_work_queue_contract(monkeypatch):
    monkeypatch.setattr(recovery, "scan_revenue_risk", lambda: RevenueScanResult("scan_test", [], 0.0))
    response = TestClient(app).post("/api/recovery/scan")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "scan_id": "scan_test",
        "cases_detected": 0,
        "total_revenue_at_risk": 0.0,
        "actions_recommended": 0,
        "cases": [],
    }
