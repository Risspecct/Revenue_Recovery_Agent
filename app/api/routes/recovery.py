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

from app.api.models import EvaluateRequest, EvaluateResponse, ExecuteResponse, ScanResponse
from app.services.recovery_service import (
    evaluate,
    evaluate_and_execute,
    execute_cached_case,
)
from app.services.revenue_scanner import get_case, get_latest_scan, scan_revenue_risk
from app.services.batch_recovery import calculate_batch_recovery

router = APIRouter(tags=["recovery"])


@router.post("/scan", response_model=ScanResponse, status_code=status.HTTP_200_OK)
async def scan_cases() -> ScanResponse:
    """Scan prepared data sources and populate the in-memory work queue."""
    try:
        result = scan_revenue_risk()
        return ScanResponse(
            scan_id=result.scan_id,
            cases_detected=result.cases_detected,
            total_revenue_at_risk=result.total_revenue_at_risk,
            actions_recommended=result.actions_recommended,
            cases=[EvaluateResponse(**case.to_dict()) for case in result.cases],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Revenue scan error: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/cases", response_model=ScanResponse, status_code=status.HTTP_200_OK)
async def get_cases() -> ScanResponse:
    """Return the latest in-memory work queue."""
    result = get_latest_scan()
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No revenue scan has run.")
    return ScanResponse(
        scan_id=result.scan_id,
        cases_detected=result.cases_detected,
        total_revenue_at_risk=result.total_revenue_at_risk,
        actions_recommended=result.actions_recommended,
        cases=[EvaluateResponse(**case.to_dict()) for case in result.cases],
    )


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


@router.post(
    "/execute/{case_id}",
    response_model=ExecuteResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute a scanned recovery case",
)
async def execute_scanned_case(case_id: str) -> ExecuteResponse:
    """Execute the selected case from the latest in-memory work queue."""
    try:
        result = execute_cached_case(case_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found in latest scan.")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution engine error: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/batch-results")
def get_batch_recovery_results():
    """
    Return historical replay recovery metrics for the latest scan.
    """
    scan = get_latest_scan()

    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No revenue scan has run.",
        )

    original_cases = {
        result.case_id: get_case(result.case_id)
        for result in scan.cases
    }

    original_cases = {
        case_id: case
        for case_id, case in original_cases.items()
        if case is not None
    }

    metrics = calculate_batch_recovery(
        decisions=scan.cases,
        original_cases=original_cases,
    )

    return {
        "status": "ok",
        "measurement_type": "historical_replay",
        "metrics": metrics.to_dict(),
    }
