"""
Unit tests — Overdue receivable domain.
"""

import pytest
from app.decision.schemas import CaseType, GuardrailStatus, Intervention, RecoveryCase
from app.decision.engine import decide
from app.decision._catalogue import CATALOGUE


def _make(case_id, amount, **ctx):
    return RecoveryCase(
        case_id=case_id,
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id="cust_rec",
        revenue_at_risk=amount,
        context=ctx,
    )


def test_normal_overdue_reminder():
    result = decide(_make("rec_001", 3_000.0, payment_status="overdue",
                          days_overdue=10, days_since_last_reminder=8))
    assert result.recommended_action == Intervention.INVOICE_REMINDER
    assert result.guardrail_status   == GuardrailStatus.APPROVED
    assert result.reason


def test_paid_invoice_no_action():
    result = decide(_make("rec_002", 5_000.0, payment_status="paid", days_overdue=0))
    assert result.recommended_action == Intervention.NO_ACTION


def test_settled_invoice_no_action():
    result = decide(_make("rec_002b", 5_000.0, payment_status="settled"))
    assert result.recommended_action == Intervention.NO_ACTION


def test_severely_overdue_escalates():
    result = decide(_make("rec_003", 2_000.0, payment_status="overdue", days_overdue=75))
    assert result.recommended_action == Intervention.ESCALATE


def test_high_value_30d_overdue_escalates():
    result = decide(_make("rec_004", 12_000.0, payment_status="overdue", days_overdue=35))
    assert result.recommended_action == Intervention.ESCALATE


def test_cooldown_no_duplicate_reminder():
    result = decide(_make("rec_005", 4_000.0, payment_status="overdue",
                          days_overdue=15, days_since_last_reminder=3))
    assert result.recommended_action == Intervention.NO_ACTION


def test_priority_account_escalates():
    result = decide(_make("rec_006", 1_000.0, payment_status="overdue",
                          days_overdue=5, is_priority_account=True))
    assert result.recommended_action == Intervention.ESCALATE


def test_enterprise_tier_30d_escalates():
    result = decide(_make("rec_007", 3_000.0, payment_status="overdue",
                          days_overdue=30, customer_tier="enterprise"))
    assert result.recommended_action == Intervention.ESCALATE


def test_guardrail_blocks_reminder_on_paid():
    from app.decision.guardrails import validate_decision
    case   = _make("rec_008", 2_000.0, payment_status="paid")
    status, reason = validate_decision(case, Intervention.INVOICE_REMINDER)
    assert status == GuardrailStatus.BLOCKED
    assert "paid" in reason.lower()


def test_guardrail_enforces_cooldown():
    from app.decision.guardrails import validate_decision
    case   = _make("rec_009", 3_000.0, payment_status="overdue", days_since_last_reminder=2)
    status, reason = validate_decision(case, Intervention.INVOICE_REMINDER)
    assert status == GuardrailStatus.BLOCKED
    assert "cooldown" in reason.lower() or "day" in reason.lower()


def test_determinism():
    def mk():
        return _make("rec_010", 3_000.0, payment_status="overdue",
                     days_overdue=20, days_since_last_reminder=10)
    r1, r2 = decide(mk()), decide(mk())
    assert r1.recommended_action == r2.recommended_action
    assert r1.risk_score         == r2.risk_score


@pytest.mark.parametrize("amount,ctx", [
    (3_000, {"payment_status": "overdue", "days_overdue": 10, "days_since_last_reminder": 9}),
    (5_000, {"payment_status": "paid"}),
    (2_000, {"payment_status": "overdue", "days_overdue": 80}),
    (500,   {"payment_status": "overdue", "days_overdue": 15, "is_priority_account": True}),
])
def test_action_always_in_catalogue(amount, ctx):
    result = decide(_make("rec_cat", amount, **ctx))
    assert result.recommended_action in CATALOGUE
