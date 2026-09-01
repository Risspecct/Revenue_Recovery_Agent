"""
Unit tests — Payment failure domain.
"""

import pytest
from app.decision.schemas import CaseType, GuardrailStatus, Intervention, RecoveryCase
from app.decision.engine import decide
from app.decision._catalogue import CATALOGUE


def _make(case_id, revenue, **ctx):
    return RecoveryCase(
        case_id=case_id,
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust_test",
        revenue_at_risk=revenue,
        context=ctx,
    )


def test_high_value_retryable():
    result = decide(_make("pay_001", 8_000.0, failure_reason="network_error", retry_count=1))
    assert result.recommended_action == Intervention.PAYMENT_RETRY
    assert result.guardrail_status   == GuardrailStatus.APPROVED
    assert result.priority.value in ("HIGH", "MEDIUM")
    assert result.reason
    assert result.recommended_action in CATALOGUE


def test_already_succeeded_no_action():
    result = decide(_make("pay_002", 5_000.0, payment_succeeded=True, failure_reason="", retry_count=0))
    assert result.recommended_action == Intervention.NO_ACTION
    assert result.guardrail_status   == GuardrailStatus.APPROVED


def test_retry_limit_high_value_escalate():
    result = decide(_make("pay_003", 7_000.0, failure_reason="network_error", retry_count=3))
    assert result.recommended_action == Intervention.ESCALATE
    assert result.guardrail_status   == GuardrailStatus.APPROVED


def test_retry_limit_low_value_alternate():
    result = decide(_make("pay_004", 1_200.0, failure_reason="network_error", retry_count=3))
    assert result.recommended_action == Intervention.ALTERNATE_PAYMENT_PROMPT
    assert result.guardrail_status   == GuardrailStatus.APPROVED


def test_low_value_no_action():
    result = decide(_make("pay_005", 200.0, failure_reason="unknown_code_xyz", retry_count=0))
    assert result.recommended_action == Intervention.NO_ACTION


def test_non_retryable_card_declined():
    result = decide(_make("pay_006", 2_000.0, failure_reason="card_declined", retry_count=0))
    assert result.recommended_action == Intervention.ALTERNATE_PAYMENT_PROMPT
    assert result.guardrail_status   == GuardrailStatus.APPROVED


def test_guardrail_blocks_retry_on_success():
    from app.decision.guardrails import validate_decision
    case   = _make("pay_007", 5_000.0, payment_succeeded=True)
    status, reason = validate_decision(case, Intervention.PAYMENT_RETRY)
    assert status == GuardrailStatus.BLOCKED
    assert "succeeded" in reason.lower()


def test_determinism():
    a = decide(_make("pay_008", 3_500.0, failure_reason="timeout", retry_count=1))
    b = decide(_make("pay_008", 3_500.0, failure_reason="timeout", retry_count=1))
    assert a.recommended_action == b.recommended_action
    assert a.priority           == b.priority
    assert a.risk_score         == b.risk_score


@pytest.mark.parametrize("revenue,failure,retry,succeeded", [
    (10_000, "network_error", 0, False),
    (500,    "card_declined", 0, False),
    (200,    "",              0, True),
    (6_000,  "timeout",       3, False),
])
def test_action_always_in_catalogue(revenue, failure, retry, succeeded):
    result = decide(_make("pay_cat", revenue, failure_reason=failure,
                          retry_count=retry, payment_succeeded=succeeded))
    assert result.recommended_action in CATALOGUE
