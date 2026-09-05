"""
Recovery Decision Engine — main orchestrator.

Architecture
------------
RecoveryCase (input)  [never mutated]
    │
    ├─ rules.py  (decide_payment / decide_checkout / decide_receivable)
    │       → candidate action + reason + confidence
    │       → effective_recovery_probability  (checkout only; others use 0.0)
    │
    ├─ guardrails.py
    │       → APPROVED, BLOCKED, or ESCALATED
    │
    ├─ Double-blocked terminal fallback → NO_ACTION
    │
    ├─ Priority classifier
    │
    ├─ Revenue reasoning
    │
    └─ DecisionResult (output)

GuardrailStatus semantics
--------------------------
APPROVED  — the recommended action passed all guardrail checks.
BLOCKED   — the action was blocked and no safe replacement was available;
            the result is NO_ACTION.
ESCALATED — the final action is ESCALATE because the decision path
            intentionally escalated the case (either via a domain rule
            or as a guardrail-triggered fallback for high-value cases).

decide() is non-mutating: the supplied RecoveryCase is never modified.
Calling decide(case) twice on the same object always produces the same result.
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
from app.decision._catalogue import THRESHOLDS
from app.decision.guardrails import validate_decision
from app.decision import rules


# ---------------------------------------------------------------------------
# Priority classification
# ---------------------------------------------------------------------------

def _classify_priority(revenue_at_risk: float, risk_score: float) -> Priority:
    if revenue_at_risk >= THRESHOLDS["revenue_high"] or risk_score >= THRESHOLDS["risk_score_high"]:
        return Priority.HIGH
    if revenue_at_risk >= THRESHOLDS["revenue_medium"] or risk_score >= THRESHOLDS["risk_score_medium"]:
        return Priority.MEDIUM
    return Priority.LOW


# ---------------------------------------------------------------------------
# Composite risk score
# ---------------------------------------------------------------------------

def _compute_risk_score(
    revenue_at_risk: float,
    risk_probability: float,
    confidence: float,
) -> float:
    rev_band = min(
        revenue_at_risk / THRESHOLDS["revenue_high"],
        1.0
    )

    score = (0.4 * rev_band + 0.4 * confidence + 0.2 * risk_probability)
    return round(min(score, 1.0), 4)

# ---------------------------------------------------------------------------
# Revenue reasoning
# ---------------------------------------------------------------------------


def _revenue_reasoning(
    recovery_probability: float,
    revenue_at_risk: float,
    intervention_lift_assumption: float | None = None,
) -> dict:
    """
    Compute propensity-weighted revenue bookkeeping.

    propensity_weighted_recovery_value
        = recovery_probability × revenue_at_risk

    This is a propensity-weighted estimate of potential recovery value.
    It is NOT a guaranteed natural-recovery figure, and it is NOT a
    causal claim about what intervention will produce.
    """
    reasoning: dict = {
        "propensity_weighted_recovery_value": round(recovery_probability * revenue_at_risk, 2),
        "note": (
            "propensity_weighted_recovery_value is recovery_probability × revenue_at_risk. "
            "It is a propensity-weighted estimate only — not guaranteed recovery "
            "and not a causal claim about intervention outcomes."
        ),
    }
    if intervention_lift_assumption is not None:
        reasoning["hypothetical_intervention_value"] = round(
            revenue_at_risk * intervention_lift_assumption, 2
        )
        reasoning["intervention_lift_assumption"] = intervention_lift_assumption
        reasoning["hypothetical_note"] = (
            "hypothetical_intervention_value is computed from a caller-supplied "
            "lift assumption and represents a hypothetical estimate only. "
            "No measured causal intervention data exists."
        )
    return reasoning


# ---------------------------------------------------------------------------
# Guardrail fallback  (fix: double-BLOCKED → terminal NO_ACTION)
# ---------------------------------------------------------------------------

def _resolve_action(
    case: RecoveryCase,
    action: Intervention,
    reason: str,
    confidence: float,
) -> tuple[Intervention, str, float, GuardrailStatus]:
    """
    Validate action through guardrails.  If blocked, attempt one safe fallback.
    If the fallback is also blocked, the terminal result is always NO_ACTION/BLOCKED.
    This prevents any infinite loop and guarantees a resolved action.

    Returns (action, reason, confidence, guardrail_status).
    """
    status, blocked_reason = validate_decision(case, action)

    if status != GuardrailStatus.BLOCKED:
        # Passed first time — assign correct status
        final_status = (
            GuardrailStatus.ESCALATED
            if action == Intervention.ESCALATE
            else GuardrailStatus.APPROVED
        )
        return action, reason, confidence, final_status

    # First action was blocked — choose a fallback
    if case.revenue_at_risk >= THRESHOLDS["revenue_high"]:
        fallback = Intervention.ESCALATE
        fallback_reason = (
            f"Preferred action was blocked by guardrail ({blocked_reason}). "
            "Escalating due to high revenue at risk."
        )
    else:
        fallback = Intervention.NO_ACTION
        fallback_reason = (
            f"Preferred action was blocked by guardrail ({blocked_reason}). "
            "Defaulting to NO_ACTION to prevent unsafe intervention."
        )

    fallback_confidence = max(confidence - 0.15, 0.30)
    fallback_status, _ = validate_decision(case, fallback)

    if fallback_status != GuardrailStatus.BLOCKED:
        final_status = (
            GuardrailStatus.ESCALATED
            if fallback == Intervention.ESCALATE
            else GuardrailStatus.APPROVED
        )
        return fallback, fallback_reason, fallback_confidence, final_status

    # Fallback also blocked — terminal safe result
    terminal_reason = (
        f"Both preferred action and fallback were blocked by guardrails "
        f"({blocked_reason}). Defaulting to NO_ACTION."
    )
    return Intervention.NO_ACTION, terminal_reason, 0.30, GuardrailStatus.BLOCKED


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decide(
    case: RecoveryCase,
    intervention_lift_assumption: float | None = None,
) -> DecisionResult:
    """
    Evaluate a RecoveryCase and return a structured DecisionResult.

    This function is non-mutating: the supplied RecoveryCase is never modified.

    Parameters
    ----------
    case : RecoveryCase
        The revenue-risk case to evaluate.
    intervention_lift_assumption : float | None
        Optional caller-supplied fraction (e.g. 0.05) used ONLY to populate
        the hypothetical revenue reasoning field.  Not used in decision logic.
    """
    # --- Route to domain rule module --------------------------------------
    # decide_checkout returns a 4-tuple (action, reason, confidence, prob).
    # All other rule functions return a 3-tuple; recovery_probability stays
    # at the case value (0.0 when no upstream model exists for that domain).
    # --- Route to domain rule module --------------------------------------
    if case.case_type == CaseType.PAYMENT_FAILURE:
        action, reason, confidence = rules.decide_payment(case)
        effective_prob = case.recovery_probability
        risk_probability = effective_prob

    elif case.case_type == CaseType.CHECKOUT_ABANDONMENT:
        action, reason, confidence, effective_prob = rules.decide_checkout(case)
        risk_probability = effective_prob

    elif case.case_type == CaseType.OVERDUE_RECEIVABLE:
        action, reason, confidence = rules.decide_receivable(case)
        effective_prob = case.recovery_probability

        # O2C model predicts late-payment risk, not recovery probability.
        risk_probability = float(
            case.context.get("late_payment_probability", 0.0)
        )

    else:
        action, reason, confidence = (
            Intervention.NO_ACTION,
            f"Unknown case type '{case.case_type}'. Defaulting to NO_ACTION.",
            0.0,
        )
        effective_prob = case.recovery_probability
        risk_probability = effective_prob

    # --- available_interventions whitelist --------------------------------
    if case.available_interventions and action not in case.available_interventions:
        blocked_name = action.value          # capture before overwriting
        action = Intervention.NO_ACTION
        reason = (
            f"Preferred action {blocked_name} is not in the case's "
            "available_interventions whitelist."
        )
        confidence = 0.50

    # --- Guardrails + fallback resolution --------------------------------
    action, reason, confidence, guardrail_status = _resolve_action(
        case, action, reason, confidence
    )

    # --- Scoring and classification (no case mutation) -------------------
    risk_score = _compute_risk_score(
        case.revenue_at_risk,
        risk_probability,
        confidence,
    )
    priority = _classify_priority(case.revenue_at_risk, risk_score)
    rev_reasoning = _revenue_reasoning(
        effective_prob, case.revenue_at_risk, intervention_lift_assumption
    )

    return DecisionResult(
        case_id=case.case_id,
        case_type=case.case_type,
        revenue_at_risk=case.revenue_at_risk,
        recovery_probability=effective_prob,
        risk_score=risk_score,
        priority=priority,
        recommended_action=action,
        reason=reason,
        confidence=round(confidence, 4),
        guardrail_status=guardrail_status,
        revenue_reasoning=rev_reasoning,
    )
