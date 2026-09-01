"""
FastAPI application entry point.

Run from the repository root:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.settings import APP_TITLE, APP_VERSION
from app.api.routes import recovery

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description=(
        "RazorPay Track 03 — Revenue Recovery Engine. "
        "Detects revenue at risk and determines the right recovery intervention."
    ),
)

app.include_router(recovery.router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "version": APP_VERSION}
