"""
Recovery service.

Thin orchestration layer between the API and the decision engine / executor.

Responsibilities
----------------
evaluate()         → RecoveryCase → decide()          → EvaluateResponse
evaluate_and_execute() → RecoveryCase → decide() → execute() → ExecuteResponse

No business logic lives here.  Rules, guardrails, and scoring are handled
by the decision engine.  Execution simulation is handled by the executor.
"""

from __future__ import annotations

from app.api.models import EvaluateRequest, EvaluateResponse, ExecuteResponse
from app.decision import engine as decision_engine
from app.decision.schemas import DecisionResult, RecoveryCase
from app.execution.executor import execute
from app.services.revenue_scanner import get_case


# ---------------------------------------------------------------------------
# Internal helper: EvaluateRequest → RecoveryCase
# ---------------------------------------------------------------------------

def _build_case(request: EvaluateRequest) -> RecoveryCase:
    return RecoveryCase(
        case_id                 = request.case_id,
        case_type               = request.case_type,
        customer_id             = request.customer_id,
        revenue_at_risk         = request.revenue_at_risk,
        recovery_probability    = request.recovery_probability,
        context                 = dict(request.context),            # defensive copy
        available_interventions = list(request.available_interventions),
    )


# ---------------------------------------------------------------------------
# Internal helper: DecisionResult → EvaluateResponse
# ---------------------------------------------------------------------------

def _to_evaluate_response(result: DecisionResult) -> EvaluateResponse:
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """
    Evaluate a single recovery case.  Decision only — no execution.

    Parameters
    ----------
    request : EvaluateRequest

    Returns
    -------
    EvaluateResponse
    """
    result = decision_engine.decide(_build_case(request))
    return _to_evaluate_response(result)


def evaluate_and_execute(request: EvaluateRequest) -> ExecuteResponse:
    """
    Evaluate a recovery case and execute the approved action (simulation).

    Decision logic lives entirely in the engine.
    Execution simulation lives entirely in the executor.
    This function only orchestrates the two.

    Parameters
    ----------
    request : EvaluateRequest

    Returns
    -------
    ExecuteResponse
        Contains the full DecisionResult and the ExecutionResult.
    """
    decision = decision_engine.decide(_build_case(request))
    execution = execute(decision)

    return ExecuteResponse(
        decision=_to_evaluate_response(decision),
        execution=execution.to_dict(),
    )


def execute_cached_case(case_id: str) -> ExecuteResponse | None:
    """Execute a case retained by the latest in-memory revenue scan."""
    case = get_case(case_id)
    if case is None:
        return None
    decision = decision_engine.decide(case)
    execution = execute(decision)
    return ExecuteResponse(
        decision=_to_evaluate_response(decision),
        execution=execution.to_dict(),
    )
