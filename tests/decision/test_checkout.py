"""
Unit tests — Checkout abandonment domain.
"""

import pytest
from app.decision.schemas import CaseType, GuardrailStatus, Intervention, RecoveryCase
from app.decision.engine import decide
from app.decision._catalogue import CATALOGUE


def _make(case_id, revenue, prob=0.0, **ctx):
    return RecoveryCase(
        case_id=case_id,
        case_type=CaseType.CHECKOUT_ABANDONMENT,
        customer_id="cust_chk",
        revenue_at_risk=revenue,
        recovery_probability=prob,
        context=ctx,
    )


def test_high_value_high_propensity_reminder():
    result = decide(_make("chk_001", 4_000.0, prob=0.72))
    assert result.recommended_action == Intervention.CHECKOUT_REMINDER
    assert result.guardrail_status   == GuardrailStatus.APPROVED
    assert result.priority.value     == "HIGH"
    assert result.reason


def test_low_propensity_low_value_no_action():
    result = decide(_make("chk_002", 100.0, prob=0.05))
    assert result.recommended_action == Intervention.NO_ACTION


def test_already_recovered_no_action():
    result = decide(_make("chk_003", 5_000.0, prob=0.90, already_recovered=True))
    assert result.recommended_action == Intervention.NO_ACTION


def test_incentivized_recovery_eligible():
    result = decide(_make("chk_004", 2_500.0, prob=0.55, incentive_eligible=True))
    assert result.recommended_action == Intervention.INCENTIVIZED_RECOVERY
    assert result.guardrail_status   == GuardrailStatus.APPROVED


def test_incentivized_recovery_ineligible_fallback():
    result = decide(_make("chk_005", 2_500.0, prob=0.55))
    assert result.recommended_action != Intervention.INCENTIVIZED_RECOVERY
    assert result.recommended_action in CATALOGUE


def test_duplicate_intervention_blocked():
    result = decide(_make("chk_006", 3_000.0, prob=0.65, intervention_already_sent=True))
    assert result.recommended_action == Intervention.NO_ACTION


def test_guardrail_blocks_incentive_without_eligibility():
    from app.decision.guardrails import validate_decision
    case   = _make("chk_007", 2_000.0, prob=0.60)
    status, reason = validate_decision(case, Intervention.INCENTIVIZED_RECOVERY)
    assert status == GuardrailStatus.BLOCKED
    assert "eligib" in reason.lower()


def test_guardrail_blocks_after_recovery():
    from app.decision.guardrails import validate_decision
    case   = _make("chk_008", 3_000.0, prob=0.80, already_recovered=True)
    status, _ = validate_decision(case, Intervention.CHECKOUT_REMINDER)
    assert status == GuardrailStatus.BLOCKED


def test_determinism():
    r1 = decide(_make("chk_009", 1_500.0, prob=0.45))
    r2 = decide(_make("chk_009", 1_500.0, prob=0.45))
    assert r1.recommended_action == r2.recommended_action
    assert r1.risk_score         == r2.risk_score


@pytest.mark.parametrize("revenue,prob,ctx", [
    (5_000, 0.80, {}),
    (50,    0.05, {}),
    (2_000, 0.55, {"incentive_eligible": True}),
    (3_000, 0.70, {"already_recovered": True}),
])
def test_action_always_in_catalogue(revenue, prob, ctx):
    result = decide(_make("chk_cat", revenue, prob=prob, **ctx))
    assert result.recommended_action in CATALOGUE
