from __future__ import annotations

import pytest

from app.decision.schemas import (
    CaseType,
    DecisionResult,
    ExecutionStatus,
    GuardrailStatus,
    Intervention,
    Priority,
)
from app.execution.executor import execute


BASE_DECISION = DecisionResult(
    case_id="case_001",
    case_type=CaseType.CHECKOUT_ABANDONMENT,
    revenue_at_risk=4000.0,
    recovery_probability=0.75,
    risk_score=0.7,
    priority=Priority.HIGH,
    recommended_action=Intervention.CHECKOUT_REMINDER,
    reason="test reason",
    confidence=0.9,
    guardrail_status=GuardrailStatus.APPROVED,
    revenue_reasoning={"note": "test"},
)


@pytest.mark.parametrize(
    "action",
    [
        Intervention.PAYMENT_RETRY,
        Intervention.ALTERNATE_PAYMENT_PROMPT,
        Intervention.CHECKOUT_REMINDER,
        Intervention.INCENTIVIZED_RECOVERY,
        Intervention.INVOICE_REMINDER,
        Intervention.ESCALATE,
    ],
)
def test_supported_actions_execute(action):
    decision = BASE_DECISION
    decision.recommended_action = action
    result = execute(decision)
    assert result.action == action
    assert result.status == ExecutionStatus.EXECUTED
    assert result.simulated is True
    assert result.message
    assert result.execution_id.startswith("exec_")
    assert result.timestamp


def test_no_action_is_skipped():
    decision = BASE_DECISION
    decision.recommended_action = Intervention.NO_ACTION
    result = execute(decision)
    assert result.action == Intervention.NO_ACTION
    assert result.status == ExecutionStatus.SKIPPED
    assert result.simulated is True
    assert result.message


def test_blocked_decision_is_rejected():
    decision = BASE_DECISION
    decision.recommended_action = Intervention.PAYMENT_RETRY
    decision.guardrail_status = GuardrailStatus.BLOCKED
    result = execute(decision)
    assert result.status == ExecutionStatus.REJECTED
    assert result.simulated is True
    assert result.message


def test_unsupported_action_rejected():
    decision = BASE_DECISION
    decision.recommended_action = "UNSUPPORTED_ACTION"  # type: ignore[assignment]
    result = execute(decision)
    assert result.status == ExecutionStatus.REJECTED
    assert result.simulated is True
    assert "unsupported" in result.message.lower() or "rejected" in result.message.lower()


def test_escalate_guardrail_escalated_executes():
    decision = BASE_DECISION
    decision.recommended_action = Intervention.ESCALATE
    decision.guardrail_status = GuardrailStatus.ESCALATED
    result = execute(decision)
    assert result.status == ExecutionStatus.EXECUTED
    assert result.action == Intervention.ESCALATE
    assert "escalat" in result.message.lower()


def test_execution_ids_and_timestamps_are_unique_and_present():
    results = [
        execute({**BASE_DECISION.__dict__, "case_id": f"case_{idx}", "recommended_action": Intervention.CHECKOUT_REMINDER, "guardrail_status": GuardrailStatus.APPROVED})
        for idx in range(3)
    ]
    ids = [r.execution_id for r in results]
    assert len(ids) == len(set(ids))
    for result in results:
        assert result.execution_id.startswith("exec_")
        assert result.timestamp
        assert result.simulated is True
