"""
Recovery Decision Engine — main orchestrator.

Architecture
------------
RecoveryCase (input)
    │
    ├─ rules.py  (decide_payment / decide_checkout / decide_receivable)
    │       → candidate action + reason + confidence
    │
    ├─ guardrails.py
    │       → APPROVED or BLOCKED (with fallback to NO_ACTION / ESCALATE)
    │
    ├─ Priority classifier
    │
    ├─ Revenue reasoning
    │
    └─ DecisionResult (output)

The engine is stateless and deterministic.
"""

from __future__ import annotations

from app.decision.schemas import (
    CaseType,
    DecisionResult,
    GuardrailStatus,
    Intervention,
    Priority,
    RecoveryCase,
)
from app.decision._catalogue import CATALOGUE, THRESHOLDS
from app.decision.guardrails import validate_decision
from app.decision import rules


# ---------------------------------------------------------------------------
# Priority classification
# ---------------------------------------------------------------------------

def _classify_priority(case: RecoveryCase, risk_score: float) -> Priority:
    amount = case.revenue_at_risk
    if amount >= THRESHOLDS["revenue_high"] or risk_score >= THRESHOLDS["risk_score_high"]:
        return Priority.HIGH
    if amount >= THRESHOLDS["revenue_medium"] or risk_score >= THRESHOLDS["risk_score_medium"]:
        return Priority.MEDIUM
    return Priority.LOW


# ---------------------------------------------------------------------------
# Composite risk score
# ---------------------------------------------------------------------------

def _compute_risk_score(case: RecoveryCase, confidence: float) -> float:
    rev_band   = min(case.revenue_at_risk / THRESHOLDS["revenue_high"], 1.0)
    propensity = case.recovery_probability
    score = 0.4 * rev_band + 0.4 * confidence + 0.2 * propensity
    return round(min(score, 1.0), 4)


# ---------------------------------------------------------------------------
# Revenue reasoning
# ---------------------------------------------------------------------------

def _revenue_reasoning(
    case: RecoveryCase,
    intervention_lift_assumption: float | None = None,
) -> dict:
    prob   = case.recovery_probability
    amount = case.revenue_at_risk
    reasoning: dict = {
        "expected_natural_recovery_value": round(prob * amount, 2),
        "note": (
            "expected_natural_recovery_value is a propensity-weighted estimate "
            "of natural recovery, not a guaranteed or causal recovery figure."
        ),
    }
    if intervention_lift_assumption is not None:
        reasoning["hypothetical_intervention_value"] = round(amount * intervention_lift_assumption, 2)
        reasoning["intervention_lift_assumption"]    = intervention_lift_assumption
        reasoning["hypothetical_note"] = (
            "hypothetical_intervention_value is computed from a caller-supplied "
            "lift assumption and represents a hypothetical estimate only. "
            "No measured causal intervention data exists."
        )
    return reasoning


# ---------------------------------------------------------------------------
# Guardrail fallback
# ---------------------------------------------------------------------------

def _safe_fallback(case: RecoveryCase, blocked_reason: str) -> tuple[Intervention, str]:
    if case.revenue_at_risk >= THRESHOLDS["revenue_high"]:
        return (
            Intervention.ESCALATE,
            f"Preferred action was blocked by guardrail ({blocked_reason}). "
            "Escalating due to high revenue at risk.",
        )
    return (
        Intervention.NO_ACTION,
        f"Preferred action was blocked by guardrail ({blocked_reason}). "
        "Defaulting to NO_ACTION to prevent unsafe intervention.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decide(
    case: RecoveryCase,
    intervention_lift_assumption: float | None = None,
) -> DecisionResult:
    """
    Evaluate a RecoveryCase and return a structured DecisionResult.

    Parameters
    ----------
    case : RecoveryCase
    intervention_lift_assumption : float | None
        Optional caller-supplied fraction used ONLY for hypothetical revenue
        reasoning. Not used in decision logic.
    """
    if case.case_type == CaseType.PAYMENT_FAILURE:
        action, reason, confidence = rules.decide_payment(case)
    elif case.case_type == CaseType.CHECKOUT_ABANDONMENT:
        action, reason, confidence = rules.decide_checkout(case)
    elif case.case_type == CaseType.OVERDUE_RECEIVABLE:
        action, reason, confidence = rules.decide_receivable(case)
    else:
        action, reason, confidence = (
            Intervention.NO_ACTION,
            f"Unknown case type '{case.case_type}'. Defaulting to NO_ACTION.",
            0.0,
        )

    if case.available_interventions and action not in case.available_interventions:
        action     = Intervention.NO_ACTION
        reason     = "Preferred action is not in the case's available_interventions whitelist."
        confidence = 0.50

    guardrail_status, guardrail_reason = validate_decision(case, action)

    if guardrail_status == GuardrailStatus.BLOCKED:
        fallback_action, fallback_reason = _safe_fallback(case, guardrail_reason)
        fallback_status, _               = validate_decision(case, fallback_action)
        action           = fallback_action
        reason           = fallback_reason
        confidence       = max(confidence - 0.15, 0.30)
        guardrail_status = fallback_status

    risk_score      = _compute_risk_score(case, confidence)
    case.risk_score = risk_score
    priority        = _classify_priority(case, risk_score)
    rev_reasoning   = _revenue_reasoning(case, intervention_lift_assumption)

    return DecisionResult(
        case_id              = case.case_id,
        case_type            = case.case_type,
        revenue_at_risk      = case.revenue_at_risk,
        recovery_probability = case.recovery_probability,
        risk_score           = risk_score,
        priority             = priority,
        recommended_action   = action,
        reason               = reason,
        confidence           = round(confidence, 4),
        guardrail_status     = guardrail_status,
        revenue_reasoning    = rev_reasoning,
    )
