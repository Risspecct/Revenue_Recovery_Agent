"""
Hardening tests — covers T1 through T12 from the audit.

These tests verify defect fixes and previously untested behaviors.
They do not duplicate the existing domain tests; they extend coverage.
"""

from __future__ import annotations

import copy

import pytest

from app.decision._catalogue import THRESHOLDS
from app.decision.engine import decide
from app.decision.schemas import (
    CaseType,
    GuardrailStatus,
    Intervention,
    Priority,
    RecoveryCase,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payment(case_id="x", revenue=3_000.0, **ctx):
    return RecoveryCase(
        case_id=case_id,
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust",
        revenue_at_risk=revenue,
        context=ctx,
    )


def _checkout(case_id="x", revenue=2_000.0, prob=0.50, **ctx):
    return RecoveryCase(
        case_id=case_id,
        case_type=CaseType.CHECKOUT_ABANDONMENT,
        customer_id="cust",
        revenue_at_risk=revenue,
        recovery_probability=prob,
        context=ctx,
    )


def _receivable(case_id="x", amount=3_000.0, **ctx):
    return RecoveryCase(
        case_id=case_id,
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id="cust",
        revenue_at_risk=amount,
        context=ctx,
    )


# ---------------------------------------------------------------------------
# T1 — Input immutability
# ---------------------------------------------------------------------------

class TestInputImmutability:
    def test_payment_case_not_mutated(self):
        case = _payment(revenue=3_000.0, failure_reason="timeout", retry_count=1)
        original = copy.deepcopy(case)
        decide(case)
        assert case.risk_score         == original.risk_score
        assert case.recovery_probability == original.recovery_probability
        assert case.context            == original.context

    def test_checkout_case_not_mutated_without_features(self):
        """No model features → model returns None → prob stays at caller value."""
        case = _checkout(revenue=2_000.0, prob=0.55)
        original_prob = case.recovery_probability
        decide(case)
        assert case.recovery_probability == original_prob
        assert case.risk_score == 0.0

    def test_checkout_case_not_mutated_with_model_features(self):
        """Model features present → model may score → case must still not be mutated."""
        case = RecoveryCase(
            case_id="chk_ml",
            case_type=CaseType.CHECKOUT_ABANDONMENT,
            customer_id="cust",
            revenue_at_risk=2_000.0,
            recovery_probability=0.99,   # would be overwritten in old code
            context={
                "cart_additions": 3, "views": 12, "unique_products": 4,
                "event_count": 25, "duration_minutes": 8.5,
                "hour_of_day": 14, "day_of_week": 2,
            },
        )
        original_prob  = case.recovery_probability
        original_score = case.risk_score
        decide(case)
        # The input case must remain unmodified regardless of model score
        assert case.recovery_probability == original_prob
        assert case.risk_score           == original_score

    def test_receivable_case_not_mutated(self):
        case = _receivable(amount=3_000.0, payment_status="overdue", days_overdue=15)
        original = copy.deepcopy(case)
        decide(case)
        assert case.risk_score           == original.risk_score
        assert case.recovery_probability == original.recovery_probability


# ---------------------------------------------------------------------------
# T2 — Double-blocked fallback resolves to NO_ACTION
# ---------------------------------------------------------------------------

class TestDoubleBlockedFallback:
    def test_double_blocked_resolves_to_no_action(self):
        """
        A paid invoice with high revenue triggers the paid-invoice guardrail.
        The fallback (_safe_fallback) tries ESCALATE for high revenue, but
        ESCALATE is also blocked by the paid-invoice guardrail.
        The terminal result must be NO_ACTION / BLOCKED — not an unresolved loop.
        """
        case = _receivable(
            amount=8_000.0,   # >= revenue_high (5000) → fallback would try ESCALATE
            payment_status="paid",
        )
        # Manually force the scenario: override the rule outcome so the rule
        # itself doesn't short-circuit to NO_ACTION before guardrails run.
        # We do this by calling _resolve_action directly.
        from app.decision.engine import _resolve_action

        action, reason, confidence, status = _resolve_action(
            case, Intervention.INVOICE_REMINDER, "test", 0.78
        )
        assert action == Intervention.NO_ACTION
        assert status == GuardrailStatus.BLOCKED
        assert "blocked" in reason.lower()

    def test_double_blocked_end_to_end_no_infinite_loop(self):
        """
        End-to-end: decide() always returns even if guardrails would block
        multiple fallbacks.  Result is a valid DecisionResult — not an exception.
        """
        case = _receivable(amount=8_000.0, payment_status="paid")
        result = decide(case)
        # Rule correctly returns NO_ACTION directly (paid status check fires first),
        # so guardrail is never triggered in the happy path —
        # but the engine must complete without error regardless.
        assert result.recommended_action in frozenset(Intervention)


# ---------------------------------------------------------------------------
# T3 — ESCALATE action produces ESCALATED guardrail status
# ---------------------------------------------------------------------------

class TestEscalatedStatus:
    def test_rule_driven_escalate_has_escalated_status(self):
        """Domain rule escalates directly (severely overdue receivable)."""
        result = decide(_receivable(amount=2_000.0, payment_status="overdue", days_overdue=75))
        assert result.recommended_action == Intervention.ESCALATE
        assert result.guardrail_status   == GuardrailStatus.ESCALATED

    def test_payment_retry_exhausted_high_value_escalated_status(self):
        """Retry exhaustion on high-value payment → ESCALATE + ESCALATED status."""
        result = decide(_payment(revenue=7_000.0, failure_reason="timeout", retry_count=3))
        assert result.recommended_action == Intervention.ESCALATE
        assert result.guardrail_status   == GuardrailStatus.ESCALATED

    def test_priority_account_receivable_escalated_status(self):
        result = decide(_receivable(
            amount=1_000.0, payment_status="overdue",
            days_overdue=5, is_priority_account=True,
        ))
        assert result.recommended_action == Intervention.ESCALATE
        assert result.guardrail_status   == GuardrailStatus.ESCALATED

    def test_approved_action_is_not_escalated(self):
        """A normal approved action must NOT carry ESCALATED status."""
        result = decide(_payment(revenue=3_000.0, failure_reason="timeout", retry_count=0))
        assert result.recommended_action == Intervention.PAYMENT_RETRY
        assert result.guardrail_status   == GuardrailStatus.APPROVED


# ---------------------------------------------------------------------------
# T4 — Invalid / unknown CaseType
# ---------------------------------------------------------------------------

class TestInvalidCaseType:
    def test_unknown_case_type_returns_no_action(self):
        case = RecoveryCase(
            case_id="bad",
            case_type="UNKNOWN_DOMAIN",   # type: ignore[arg-type]
            customer_id="cust",
            revenue_at_risk=1_000.0,
        )
        result = decide(case)
        assert result.recommended_action == Intervention.NO_ACTION
        assert result.guardrail_status   == GuardrailStatus.APPROVED
        assert "unknown" in result.reason.lower()


# ---------------------------------------------------------------------------
# T5 — Empty failure reason is configurable
# ---------------------------------------------------------------------------

class TestEmptyFailureReason:
    def test_empty_reason_retryable_by_default(self):
        """Default config: empty failure_reason is treated as retryable."""
        assert THRESHOLDS["empty_failure_reason_retryable"] is True
        result = decide(_payment(revenue=3_000.0, retry_count=0))
        # No failure_reason supplied → empty string → retryable
        assert result.recommended_action == Intervention.PAYMENT_RETRY

    def test_empty_reason_respects_flag(self, monkeypatch):
        """When flag is False, empty failure_reason is not retryable."""
        monkeypatch.setitem(THRESHOLDS, "empty_failure_reason_retryable", False)
        case = _payment(revenue=3_000.0, retry_count=0)
        # No failure_reason → empty string → non-retryable with flag off
        result = decide(case)
        # Falls through to low-value / fallback path — must NOT be PAYMENT_RETRY
        assert result.recommended_action != Intervention.PAYMENT_RETRY

    def test_known_retryable_reason_unaffected_by_flag(self, monkeypatch):
        """Named retryable reasons (e.g. 'timeout') work regardless of the flag."""
        monkeypatch.setitem(THRESHOLDS, "empty_failure_reason_retryable", False)
        result = decide(_payment(revenue=3_000.0, failure_reason="timeout", retry_count=0))
        assert result.recommended_action == Intervention.PAYMENT_RETRY


# ---------------------------------------------------------------------------
# T6 — available_interventions whitelist
# ---------------------------------------------------------------------------

class TestAvailableInterventionsWhitelist:
    def test_allowed_action_passes_through(self):
        case = _payment(
            revenue=3_000.0, failure_reason="timeout", retry_count=0,
        )
        case.available_interventions = [Intervention.PAYMENT_RETRY, Intervention.ESCALATE]
        result = decide(case)
        assert result.recommended_action == Intervention.PAYMENT_RETRY

    def test_blocked_action_replaced_with_no_action(self):
        case = _checkout(revenue=4_000.0, prob=0.72)
        case.available_interventions = [Intervention.NO_ACTION]
        result = decide(case)
        assert result.recommended_action == Intervention.NO_ACTION

    def test_blocked_reason_contains_action_name(self):
        """Reason must name the blocked action (fix #5)."""
        case = _checkout(revenue=4_000.0, prob=0.72)
        case.available_interventions = [Intervention.NO_ACTION]
        result = decide(case)
        # The rule would have chosen CHECKOUT_REMINDER; its name must appear in reason
        assert "CHECKOUT_REMINDER" in result.reason


# ---------------------------------------------------------------------------
# T7 — Hypothetical intervention lift
# ---------------------------------------------------------------------------

class TestHypotheticalInterventionLift:
    def test_lift_is_labelled_hypothetical(self):
        case = _checkout(revenue=1_000.0, prob=0.50)
        result = decide(case, intervention_lift_assumption=0.05)
        rr = result.revenue_reasoning
        assert "hypothetical_intervention_value" in rr
        assert "hypothetical_note" in rr
        assert "hypothetical" in rr["hypothetical_note"].lower()

    def test_lift_value_is_correct(self):
        case = _checkout(revenue=1_000.0, prob=0.50)
        result = decide(case, intervention_lift_assumption=0.05)
        assert result.revenue_reasoning["hypothetical_intervention_value"] == 50.0

    def test_no_lift_when_assumption_absent(self):
        case = _checkout(revenue=1_000.0, prob=0.50)
        result = decide(case)
        assert "hypothetical_intervention_value" not in result.revenue_reasoning

    def test_lift_not_presented_as_measured_revenue(self):
        case = _checkout(revenue=1_000.0, prob=0.50)
        result = decide(case, intervention_lift_assumption=0.10)
        note = result.revenue_reasoning.get("hypothetical_note", "")
        # Must not claim this is measured or guaranteed
        assert "measured" not in note.lower() or "no measured" in note.lower()


# ---------------------------------------------------------------------------
# T8 — Edge cases: zero revenue, probability boundaries
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_revenue_at_risk(self):
        """Engine must not raise on zero revenue."""
        result = decide(_payment(revenue=0.0, failure_reason="timeout", retry_count=0))
        assert result.recommended_action in frozenset(Intervention)
        assert result.risk_score >= 0.0

    def test_recovery_probability_zero(self):
        result = decide(_checkout(revenue=4_000.0, prob=0.0))
        assert result.recommended_action in frozenset(Intervention)
        assert result.recovery_probability == 0.0

    def test_recovery_probability_one(self):
        result = decide(_checkout(revenue=4_000.0, prob=1.0))
        assert result.recommended_action in frozenset(Intervention)
        assert result.recovery_probability == 1.0


# ---------------------------------------------------------------------------
# T9 — Checkout ML probability: used for decision, case not mutated
# ---------------------------------------------------------------------------

class TestCheckoutMLProbability:
    _FULL_FEATURES = {
        "cart_additions": 3, "views": 12, "unique_products": 4,
        "event_count": 25, "duration_minutes": 8.5,
        "hour_of_day": 14, "day_of_week": 2,
    }

    def test_model_score_used_when_features_present(self):
        """
        With a very low manually supplied prob but full features, the model
        may return a different value.  Either way the result must be a valid
        DecisionResult — we confirm no exception is raised and the output prob
        is in [0, 1].
        """
        case = RecoveryCase(
            case_id="ml_t9",
            case_type=CaseType.CHECKOUT_ABANDONMENT,
            customer_id="cust",
            revenue_at_risk=2_000.0,
            recovery_probability=0.01,
            context=self._FULL_FEATURES,
        )
        result = decide(case)
        assert 0.0 <= result.recovery_probability <= 1.0
        assert result.recommended_action in frozenset(Intervention)

    def test_input_case_not_mutated_after_model_score(self):
        case = RecoveryCase(
            case_id="ml_t9b",
            case_type=CaseType.CHECKOUT_ABANDONMENT,
            customer_id="cust",
            revenue_at_risk=2_000.0,
            recovery_probability=0.99,
            context=self._FULL_FEATURES,
        )
        original_prob  = case.recovery_probability
        original_score = case.risk_score
        decide(case)
        assert case.recovery_probability == original_prob,  "recovery_probability was mutated"
        assert case.risk_score           == original_score, "risk_score was mutated"

    def test_result_prob_reflects_model_not_input(self):
        """
        When model features are present the result's recovery_probability should
        reflect the model's output (whatever it is), not necessarily the caller's
        manually supplied 0.99.
        """
        from app.models.checkout_recovery import score_checkout_case
        model_score = score_checkout_case(self._FULL_FEATURES)
        case = RecoveryCase(
            case_id="ml_t9c",
            case_type=CaseType.CHECKOUT_ABANDONMENT,
            customer_id="cust",
            revenue_at_risk=2_000.0,
            recovery_probability=0.99,
            context=self._FULL_FEATURES,
        )
        result = decide(case)
        if model_score is not None:
            assert abs(result.recovery_probability - model_score) < 1e-9


# ---------------------------------------------------------------------------
# T10 — Missing receivable payment_status
# ---------------------------------------------------------------------------

class TestMissingReceivablePaymentStatus:
    def test_no_payment_status_falls_through_to_reminder(self):
        """
        When payment_status is absent the rule treats it as non-paid
        and falls through to INVOICE_REMINDER (assuming not overdue enough
        to escalate and no recent reminder).
        """
        case = _receivable(
            amount=2_000.0,
            days_overdue=10,
            days_since_last_reminder=8,
            # payment_status intentionally absent
        )
        result = decide(case)
        # Must not error; most likely produces INVOICE_REMINDER or NO_ACTION
        assert result.recommended_action in frozenset(Intervention)
        # Specifically: empty status != "paid"/"settled" so reminder is valid
        assert result.recommended_action == Intervention.INVOICE_REMINDER


# ---------------------------------------------------------------------------
# T11 — DecisionResult serialization completeness
# ---------------------------------------------------------------------------

class TestDecisionResultSerialization:
    _REQUIRED_FIELDS = {
        "case_id":               str,
        "case_type":             str,
        "revenue_at_risk":       float,
        "recovery_probability":  float,
        "risk_score":            float,
        "priority":              str,
        "recommended_action":    str,
        "reason":                str,
        "confidence":            float,
        "guardrail_status":      str,
        "revenue_reasoning":     dict,
    }

    def test_to_dict_contains_all_required_fields(self):
        result = decide(_checkout(revenue=2_000.0, prob=0.50))
        d = result.to_dict()
        for field, expected_type in self._REQUIRED_FIELDS.items():
            assert field in d, f"Missing field: {field}"
            assert isinstance(d[field], expected_type), (
                f"Field '{field}' expected {expected_type.__name__}, "
                f"got {type(d[field]).__name__}"
            )

    def test_enum_fields_are_plain_strings(self):
        """to_dict() must return .value strings, not Enum instances."""
        result = decide(_payment(revenue=3_000.0, failure_reason="timeout", retry_count=0))
        d = result.to_dict()
        assert d["case_type"]           == "PAYMENT_FAILURE"
        assert d["guardrail_status"]    in ("APPROVED", "BLOCKED", "ESCALATED")
        assert d["priority"]            in ("HIGH", "MEDIUM", "LOW")
        assert d["recommended_action"]  in {i.value for i in Intervention}

    def test_revenue_reasoning_extension_is_present(self):
        result = decide(_checkout(revenue=1_000.0, prob=0.5), intervention_lift_assumption=0.05)
        d = result.to_dict()
        assert "revenue_reasoning" in d
        assert "hypothetical_intervention_value" in d["revenue_reasoning"]

    def test_revenue_reasoning_key_is_propensity_weighted(self):
        """Key name must reflect propensity-weighted estimate, not guaranteed recovery."""
        result = decide(_checkout(revenue=1_000.0, prob=0.5))
        rr = result.revenue_reasoning
        assert "propensity_weighted_recovery_value" in rr
        assert "expected_natural_recovery_value" not in rr


# ---------------------------------------------------------------------------
# T12 — LOW priority path
# ---------------------------------------------------------------------------

class TestLowPriority:
    def test_low_revenue_low_propensity_produces_low_priority(self):
        """
        revenue_at_risk well below revenue_medium (1000) and risk_score well
        below risk_score_medium (0.30) → LOW priority.
        """
        case = RecoveryCase(
            case_id="low_p",
            case_type=CaseType.PAYMENT_FAILURE,
            customer_id="cust",
            revenue_at_risk=100.0,    # << 1000
            recovery_probability=0.0,
            context={"payment_succeeded": True},  # NO_ACTION → confidence 1.0
        )
        result = decide(case)
        # risk_score = 0.4*(100/5000) + 0.4*1.0 + 0.2*0.0 = 0.008 + 0.4 = 0.408
        # → MEDIUM because risk_score >= 0.30 ...
        # Use a truly low-confidence case instead:
        case2 = RecoveryCase(
            case_id="low_p2",
            case_type=CaseType.PAYMENT_FAILURE,
            customer_id="cust",
            revenue_at_risk=100.0,
            recovery_probability=0.0,
            context={"failure_reason": "unknown_xyz", "retry_count": 0},
        )
        result2 = decide(case2)
        # revenue=100 << 1000, confidence=0.60, risk_score = 0.4*0.02 + 0.4*0.60 + 0 = 0.248
        # → LOW (below risk_score_medium 0.30 and below revenue_medium 1000)
        assert result2.priority == Priority.LOW

    def test_low_priority_result_is_valid(self):
        """LOW priority result still carries a valid action and reason."""
        case = RecoveryCase(
            case_id="low_p3",
            case_type=CaseType.PAYMENT_FAILURE,
            customer_id="cust",
            revenue_at_risk=100.0,
            recovery_probability=0.0,
            context={"failure_reason": "unknown_xyz", "retry_count": 0},
        )
        result = decide(case)
        assert result.priority           == Priority.LOW
        assert result.recommended_action in frozenset(Intervention)
        assert result.reason
        assert result.guardrail_status   in frozenset(GuardrailStatus)
