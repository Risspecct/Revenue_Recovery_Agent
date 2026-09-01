"""
Recovery API routes.

Endpoints:
  POST /api/recovery/evaluate   — evaluate a single revenue-risk case
  POST /api/recovery/execute    — evaluate and execute the approved action

The route delegates all business logic to the recovery service.
It is responsible only for HTTP concerns: request parsing, error mapping,
and response serialisation.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.models import EvaluateRequest, EvaluateResponse, ExecuteResponse
from app.services.recovery_service import evaluate, evaluate_and_execute

router = APIRouter(tags=["recovery"])


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate a revenue-risk case",
    description=(
        "Submit a single revenue-risk case (payment failure, checkout abandonment, "
        "or overdue receivable) and receive a deterministic recovery decision."
    ),
)
async def evaluate_case(request: EvaluateRequest) -> EvaluateResponse:
    """
    Evaluate a recovery case and return a decision result.

    Pydantic validates the request body before this handler is called.
    Business-rule errors (e.g. unknown context fields) are handled gracefully
    by the decision engine — they do not raise HTTP errors.
    """
    try:
        return evaluate(request)
    except Exception as exc:
        # Surface unexpected engine errors as 500 without leaking stack traces.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Decision engine error: {type(exc).__name__}: {exc}",
        ) from exc


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate and execute a bounded simulated recovery action",
    description=(
        "Submit a recovery case, receive the decision, and then execute only the "
        "approved action through the bounded simulation layer."
    ),
)
async def execute_case(request: EvaluateRequest) -> ExecuteResponse:
    """
    Evaluate a recovery case and execute the approved action via the bounded
    executor. The decision engine remains authoritative.
    """
    try:
        return evaluate_and_execute(request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution engine error: {type(exc).__name__}: {exc}",
        ) from exc
