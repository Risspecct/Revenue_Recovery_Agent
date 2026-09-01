"""
Pydantic models for the Recovery API HTTP boundary.

These are deliberately separate from the engine's dataclasses:
  - RecoveryCase / DecisionResult live in app.decision.schemas (engine contracts)
  - EvaluateRequest / EvaluateResponse live here (HTTP I/O contracts)

The service layer is responsible for converting between the two.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.decision.schemas import CaseType, GuardrailStatus, Intervention, Priority


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    """
    HTTP request body for POST /api/recovery/evaluate.

    Mirrors the fields that RecoveryCase accepts, with API-boundary validation.
    """

    case_id:   str = Field(..., min_length=1, description="Unique case identifier.")
    case_type: CaseType = Field(..., description="Revenue-risk domain.")
    customer_id: str = Field(..., min_length=1, description="Customer or account identifier.")

    revenue_at_risk: float = Field(
        ...,
        ge=0.0,
        description="Gross revenue value exposed (must be ≥ 0).",
    )
    recovery_probability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Upstream propensity score in [0, 1].",
    )

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific signals (see decision engine documentation).",
    )

    available_interventions: list[Intervention] = Field(
        default_factory=list,
        description=(
            "Optional whitelist of permitted interventions for this case. "
            "Empty list means all catalogue actions are permitted."
        ),
    )

    model_config = {"use_enum_values": False}

    @field_validator("case_id", "customer_id")
    @classmethod
    def _no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @field_validator("available_interventions", mode="before")
    @classmethod
    def _deduplicate_interventions(cls, v: list) -> list:
        # Preserve order, remove duplicates.
        seen: set = set()
        result = []
        for item in v:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class EvaluateResponse(BaseModel):
    """
    HTTP response body for POST /api/recovery/evaluate.

    All enum fields are serialised as plain strings for a stable JSON contract.
    revenue_reasoning is preserved so callers can inspect propensity-weighted
    bookkeeping without needing a separate endpoint.
    """

    case_id:              str
    case_type:            str
    revenue_at_risk:      float
    recovery_probability: float
    risk_score:           float
    priority:             str
    recommended_action:   str
    reason:               str
    confidence:           float
    guardrail_status:     str
    revenue_reasoning:    dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Health response
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status:  str
    version: str
