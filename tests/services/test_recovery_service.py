from __future__ import annotations

from app.api.models import EvaluateRequest
from app.decision.schemas import CaseType, GuardrailStatus, Intervention, RecoveryCase
from app.services.recovery_service import evaluate, evaluate_and_execute


PAYLOAD = {
    "case_id": "svc_pay_001",
    "case_type": "PAYMENT_FAILURE",
    "customer_id": "cust_1",
    "revenue_at_risk": 5000.0,
    "context": {"failure_reason": "network_error", "retry_count": 1},
}


def test_evaluate_works_without_execution():
    response = evaluate(EvaluateRequest(**PAYLOAD))
    assert response.case_id == "svc_pay_001"
    assert response.recommended_action in {"PAYMENT_RETRY", "ALTERNATE_PAYMENT_PROMPT", "ESCALATE", "NO_ACTION"}
    assert response.guardrail_status in {"APPROVED", "ESCALATED", "BLOCKED"}


def test_execute_flow_returns_both_decision_and_execution():
    response = evaluate_and_execute(EvaluateRequest(**PAYLOAD))
    assert "decision" in response.model_dump()
    assert "execution" in response.model_dump()
    assert response.decision.case_id == "svc_pay_001"
    assert response.execution["case_id"] == "svc_pay_001"
    assert response.execution["simulated"] is True


def test_blocked_decision_is_rejected_in_execution():
    blocked = RecoveryCase(
        case_id="svc_blocked",
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust_1",
        revenue_at_risk=2000.0,
        context={"failure_reason": "network_error", "retry_count": 1},
    )
    from app.decision import engine
    original = engine.decide
    try:
        engine.decide = lambda case, intervention_lift_assumption=None: __import__("app.decision.schemas", fromlist=["DecisionResult"]).DecisionResult(
            case_id=case.case_id,
            case_type=case.case_type,
            revenue_at_risk=case.revenue_at_risk,
            recovery_probability=case.recovery_probability,
            risk_score=0.0,
            priority=__import__("app.decision.schemas", fromlist=["Priority"]).Priority.MEDIUM,
            recommended_action=Intervention.PAYMENT_RETRY,
            reason="blocked",
            confidence=0.9,
            guardrail_status=GuardrailStatus.BLOCKED,
        )
        response = evaluate_and_execute(EvaluateRequest(**{
            "case_id": "svc_blocked",
            "case_type": "PAYMENT_FAILURE",
            "customer_id": "cust_1",
            "revenue_at_risk": 2000.0,
            "context": {"failure_reason": "network_error", "retry_count": 1},
        }))
        assert response.execution["status"] == "REJECTED"
        assert response.execution["simulated"] is True
    finally:
        engine.decide = original
