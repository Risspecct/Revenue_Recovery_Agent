"""
LLM analyst for bounded recovery decisions.

The analyst explains an already-approved decision and can prepare a
customer-facing recovery message.

It does NOT:
- choose the intervention,
- override guardrails,
- modify the DecisionResult,
- claim that revenue was recovered.

The initial implementation is deterministic. An LLM provider can be
plugged in behind this contract later.
"""

from __future__ import annotations

from app.decision.schemas import DecisionResult, Intervention


def _build_explanation(decision: DecisionResult) -> str:
    """Create a concise human-readable explanation from the decision."""

    return (
        f"{decision.case_type.value.replace('_', ' ').title()} case "
        f"with ₹{decision.revenue_at_risk:,.2f} at risk. "
        f"The decision engine classified it as {decision.priority.value} priority "
        f"and recommended {decision.recommended_action.value.replace('_', ' ').lower()}. "
        f"{decision.reason}"
    )


def _build_customer_message(decision: DecisionResult) -> str:
    """Create a bounded customer-facing message for supported actions."""

    messages = {
        Intervention.PAYMENT_RETRY: (
            "We couldn't complete your payment. Please retry the payment "
            "using the available payment option."
        ),
        Intervention.ALTERNATE_PAYMENT_PROMPT: (
            "Your recent payment could not be completed. Please try another "
            "available payment method."
        ),
        Intervention.CHECKOUT_REMINDER: (
            "You left an item in your checkout. You can return to complete "
            "your purchase when you're ready."
        ),
        Intervention.INCENTIVIZED_RECOVERY: (
            "You have an unfinished purchase. Please return to checkout to "
            "complete your order."
        ),
        Intervention.INVOICE_REMINDER: (
            "This is a reminder that an invoice remains outstanding. "
            "Please review the invoice and complete payment when convenient."
        ),
        Intervention.ESCALATE: (
            "Your account requires additional attention. Our team will "
            "follow up regarding the outstanding issue."
        ),
        Intervention.NO_ACTION: "",
    }

    return messages.get(decision.recommended_action, "")


def analyze_decision(decision: DecisionResult) -> dict[str, str]:
    """
    Analyze an already-approved decision.

    Returns explanation and customer-facing message without changing
    the underlying decision.
    """
    return {
        "explanation": _build_explanation(decision),
        "customer_message": _build_customer_message(decision),
    }
