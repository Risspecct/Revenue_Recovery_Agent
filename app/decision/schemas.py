"""
Common case schema for the Recovery Decision Engine.

Every revenue-risk case — regardless of domain — is normalized into a
RecoveryCase before being passed to the engine.  The `context` dict holds
domain-specific signals that the rule modules know how to interpret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class CaseType(str, Enum):
    PAYMENT_FAILURE       = "PAYMENT_FAILURE"
    CHECKOUT_ABANDONMENT  = "CHECKOUT_ABANDONMENT"
    OVERDUE_RECEIVABLE    = "OVERDUE_RECEIVABLE"


class Intervention(str, Enum):
    PAYMENT_RETRY             = "PAYMENT_RETRY"
    ALTERNATE_PAYMENT_PROMPT  = "ALTERNATE_PAYMENT_PROMPT"
    CHECKOUT_REMINDER         = "CHECKOUT_REMINDER"
    INCENTIVIZED_RECOVERY     = "INCENTIVIZED_RECOVERY"
    INVOICE_REMINDER          = "INVOICE_REMINDER"
    ESCALATE                  = "ESCALATE"
    NO_ACTION                 = "NO_ACTION"


class Priority(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"


class GuardrailStatus(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED  = "BLOCKED"


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

@dataclass
class RecoveryCase:
    """
    Normalized representation of a single revenue-risk case.

    Fields
    ------
    case_id                 : Unique identifier for this case.
    case_type               : Domain (payment / checkout / receivable).
    customer_id             : Customer or account identifier.
    revenue_at_risk         : Gross revenue value exposed (INR or unit currency).
    recovery_probability    : Propensity score from an upstream model (0–1).
                              For PAYMENT_FAILURE and OVERDUE_RECEIVABLE this
                              may be set to 0.0 when no model score is available.
    risk_score              : Composite risk score produced by the engine (0–1).
                              Leave as 0.0 on input; the engine will populate it.
    urgency                 : Optional free-text urgency signal ("HIGH" / "MEDIUM"
                              / "LOW", or domain-specific strings).
    context                 : Domain-specific signals (see rule modules for keys).
    available_interventions : Whitelist of interventions allowed for this case.
                              If empty, the engine uses the full catalogue.
    """
    case_id:                 str
    case_type:               CaseType
    customer_id:             str
    revenue_at_risk:         float
    recovery_probability:    float          = 0.0
    risk_score:              float          = 0.0
    urgency:                 str            = ""
    context:                 dict[str, Any] = field(default_factory=dict)
    available_interventions: list[Intervention] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

@dataclass
class DecisionResult:
    """
    Structured output produced by the engine for every case.

    revenue_reasoning holds natural-recovery bookkeeping; any
    hypothetical intervention-lift values are explicitly labelled and
    controlled by a caller-supplied assumption (not baked in).
    """
    case_id:              str
    case_type:            CaseType
    revenue_at_risk:      float
    recovery_probability: float
    risk_score:           float
    priority:             Priority
    recommended_action:   Intervention
    reason:               str
    confidence:           float
    guardrail_status:     GuardrailStatus
    revenue_reasoning:    dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id":              self.case_id,
            "case_type":            self.case_type.value,
            "revenue_at_risk":      self.revenue_at_risk,
            "recovery_probability": self.recovery_probability,
            "risk_score":           self.risk_score,
            "priority":             self.priority.value,
            "recommended_action":   self.recommended_action.value,
            "reason":               self.reason,
            "confidence":           self.confidence,
            "guardrail_status":     self.guardrail_status.value,
            "revenue_reasoning":    self.revenue_reasoning,
        }
