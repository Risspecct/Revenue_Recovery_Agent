"""
FastAPI application entry point.

Run from the repository root:
    uvicorn app.main:app --reload

Endpoints:
    GET  /health                    — liveness check
    POST /api/recovery/evaluate     — evaluate a revenue-risk case
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.models import HealthResponse
from app.api.routes import recovery
from app.config.settings import APP_TITLE, APP_VERSION

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description=(
        "RazorPay Track 03 — Revenue Recovery Engine. "
        "Detects revenue at risk and determines the right recovery intervention."
    ),
)

# Register the recovery router under /api/recovery
app.include_router(recovery.router, prefix="/api/recovery")


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION)
