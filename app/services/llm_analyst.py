"""
LLM analyst for bounded recovery decisions.

Gemini explains an already-approved recovery decision and prepares a
customer-facing message.

The LLM does NOT:
- choose the intervention,
- override guardrails,
- modify the DecisionResult,
- claim that revenue was recovered.

If Gemini is unavailable or returns invalid output, deterministic
fallback content is returned.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from google import genai

from app.decision.schemas import DecisionResult, Intervention


load_dotenv()

_MODEL = "gemini-3.6-flash"


def _build_fallback_explanation(decision: DecisionResult) -> str:
    return (
        f"{decision.case_type.value.replace('_', ' ').title()} case "
        f"with ₹{decision.revenue_at_risk:,.2f} at risk. "
        f"The decision engine classified it as {decision.priority.value} priority "
        f"and recommended "
        f"{decision.recommended_action.value.replace('_', ' ').lower()}. "
        f"{decision.reason}"
    )


def _build_fallback_customer_message(decision: DecisionResult) -> str:
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


def _build_prompt(decision: DecisionResult) -> str:
    context_summary = json.dumps(decision.revenue_reasoning, ensure_ascii=False,)
    return f"""
        You are a recovery analyst inside a revenue recovery system.
    
        Your role is ONLY to explain an already-made decision and draft a
        customer-facing message.
    
        You are NOT the decision-maker.
    
        You MUST NOT:
        - change the recommended action,
        - suggest a different intervention,
        - override guardrails,
        - invent customer information,
        - invent payment or invoice details,
        - claim that revenue has already been recovered,
        - claim that an intervention is guaranteed to succeed.
    
        The deterministic decision engine has already selected this action:
    
        Case type: {decision.case_type.value}
        Revenue at risk: ₹{decision.revenue_at_risk:,.2f}
        Recovery probability: {decision.recovery_probability:.4f}
        Risk score: {decision.risk_score:.4f}
        Priority: {decision.priority.value}
        Recommended action: {decision.recommended_action.value}
        Guardrail status: {decision.guardrail_status.value}
        Decision reason: {decision.reason}
    
        Additional quantified reasoning:
        {context_summary}
    
        Your explanation should synthesize the available signals rather than
        merely repeat the decision reason. Explain:
        1. what makes this case worth attention,
        2. what the model/risk signals indicate,
        3. why the EXISTING recommended action is appropriate.

        Do not introduce facts that are not present in the supplied information.

        Return ONLY valid JSON with exactly these fields:

        {{
          "explanation": "A concise operational explanation of the existing decision.",
          "customer_message": "The customer message must only describe the approved action and the relevant situation. Do not invent support channels, discounts, deadlines, order details, names, amounts, or promises."
        }}

        The explanation is for an operations user.
        The customer message must not contain invented amounts, names, dates,
        payment details, or promises of successful recovery.
        """.strip()


def _call_gemini(decision: DecisionResult) -> dict[str, str] | None:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=_MODEL,
            contents=_build_prompt(decision),
            config={
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        )

        data = json.loads(response.text)

        explanation = data.get("explanation")
        customer_message = data.get("customer_message")

        if not isinstance(explanation, str):
            return None

        if not isinstance(customer_message, str):
            return None

        return {
            "explanation": explanation.strip(),
            "customer_message": customer_message.strip(),
        }

    except Exception as exc:
        print(f"GEMINI ANALYST ERROR: {exc}")
        return None


def analyze_decision(decision: DecisionResult) -> dict[str, str]:
    """
    Analyze an already-approved decision.

    Gemini is used when available. Otherwise deterministic fallback
    content is returned.

    The underlying DecisionResult is never modified.
    """

    result = _call_gemini(decision)

    if result is not None:
        return result

    return {
        "explanation": _build_fallback_explanation(decision),
        "customer_message": _build_fallback_customer_message(decision),
    }
