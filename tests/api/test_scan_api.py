from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import recovery
from app.main import app
from app.api.models import EvaluateResponse, ExecuteResponse
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


def test_cases_endpoint_returns_latest_queue(monkeypatch):
    result = RevenueScanResult("scan_test", [], 0.0)
    monkeypatch.setattr(recovery, "get_latest_scan", lambda: result)
    response = TestClient(app).get("/api/recovery/cases")
    assert response.status_code == 200
    assert response.json()["scan_id"] == "scan_test"


def test_execute_scanned_case_uses_case_id(monkeypatch):
    expected = ExecuteResponse(
        decision=EvaluateResponse(
            case_id="checkout_1", case_type="CHECKOUT_ABANDONMENT",
            revenue_at_risk=0.0, recovery_probability=0.5, risk_score=0.2,
            priority="LOW", recommended_action="NO_ACTION", reason="test",
            confidence=0.5, guardrail_status="APPROVED",
        ),
        execution={"case_id": "checkout_1", "simulated": True},
    )
    monkeypatch.setattr(recovery, "execute_cached_case", lambda case_id: expected)
    response = TestClient(app).post("/api/recovery/execute/checkout_1")
    assert response.status_code == 200
    assert response.json()["decision"]["case_id"] == "checkout_1"
    assert response.json()["execution"]["simulated"] is True


def test_execute_scanned_case_returns_404_for_unknown_case(monkeypatch):
    monkeypatch.setattr(recovery, "execute_cached_case", lambda case_id: None)
    response = TestClient(app).post("/api/recovery/execute/missing")
    assert response.status_code == 404


def test_scan_then_execute_actionable_o2c_case():
    client = TestClient(app)
    scan = client.post("/api/recovery/scan")
    assert scan.status_code == 200

    scanned_case = next(
        case
        for case in scan.json()["cases"]
        if case["case_type"] == "OVERDUE_RECEIVABLE"
        and case["recommended_action"] in {"INVOICE_REMINDER", "ESCALATE"}
        and case["guardrail_status"] != "BLOCKED"
    )
    case_id = scanned_case["case_id"]
    recommended_action = scanned_case["recommended_action"]

    execution = client.post(f"/api/recovery/execute/{case_id}")

    assert execution.status_code == 200
    body = execution.json()
    assert body["decision"]["case_id"] == case_id
    assert body["decision"]["recommended_action"] == recommended_action
    assert body["execution"]["action"] == recommended_action
    assert body["execution"]["status"] == "EXECUTED"
