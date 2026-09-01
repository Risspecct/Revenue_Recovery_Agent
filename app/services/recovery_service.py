"""
Recovery service.

Thin orchestration layer between the API and the decision engine.
Responsibilities:
  1. Convert EvaluateRequest → RecoveryCase
  2. Call decide()
  3. Convert DecisionResult → EvaluateResponse

No business logic lives here — rules, guardrails, and scoring are all
handled by the decision engine.
"""

from __future__ import annotations

from app.api.models import EvaluateRequest, EvaluateResponse
from app.decision.engine import decide
from app.decision.schemas import RecoveryCase


def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """
    Evaluate a single recovery case.

    Parameters
    ----------
    request : EvaluateRequest
        Validated API request.

    Returns
    -------
    EvaluateResponse
        Serialisable decision result.
    """
    case = RecoveryCase(
        case_id                 = request.case_id,
        case_type               = request.case_type,
        customer_id             = request.customer_id,
        revenue_at_risk         = request.revenue_at_risk,
        recovery_probability    = request.recovery_probability,
        context                 = dict(request.context),       # defensive copy
        available_interventions = list(request.available_interventions),
    )

    result = decide(case)

    return EvaluateResponse(
        case_id              = result.case_id,
        case_type            = result.case_type.value,
        revenue_at_risk      = result.revenue_at_risk,
        recovery_probability = result.recovery_probability,
        risk_score           = result.risk_score,
        priority             = result.priority.value,
        recommended_action   = result.recommended_action.value,
        reason               = result.reason,
        confidence           = result.confidence,
        guardrail_status     = result.guardrail_status.value,
        revenue_reasoning    = result.revenue_reasoning,
    )
