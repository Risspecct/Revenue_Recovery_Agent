"""
Domain-specific decision rules for all three revenue-risk domains.

Each public decide() function returns (action, reason, confidence).
Rule modules are pure functions — no side effects, fully deterministic.
"""

from __future__ import annotations

from app.decision.schemas import Intervention, RecoveryCase
from app.decision._catalogue import THRESHOLDS
from app.models.checkout_recovery import score_checkout_case


# ===========================================================================
# Payment failure rules
# ===========================================================================

# Failure codes that are worth retrying automatically.
_RETRYABLE_FAILURES = {
    "network_error", "timeout", "bank_unavailable",
    "temporary_failure", "unknown", "",
}

# Failure codes that suggest a different payment method is needed.
_METHOD_CHANGE_FAILURES = {
    "card_declined", "do_not_honor", "card_expired",
    "lost_card", "stolen_card", "card_velocity_exceeded",
}

# Failure codes that indicate a genuine account/fund problem.
_FUND_FAILURES = {"insufficient_funds", "credit_limit_exceeded"}


def decide_payment(case: RecoveryCase) -> tuple[Intervention, str, float]:
    """Payment-failure decision rules."""
    ctx = case.context
    amount      = case.revenue_at_risk
    max_retries = THRESHOLDS["payment_max_retries"]
    high_value  = THRESHOLDS["payment_high_value"]
    low_value   = THRESHOLDS["payment_low_value"]

    succeeded   = ctx.get("payment_succeeded", False)
    retry_count = int(ctx.get("retry_count", 0))
    failure_raw = str(ctx.get("failure_reason", "")).lower().strip()

    if succeeded:
        return (
            Intervention.NO_ACTION,
            "Payment has already succeeded; no recovery action required.",
            1.0,
        )

    retryable = failure_raw in _RETRYABLE_FAILURES
    exhausted  = retry_count >= max_retries

    if retryable and not exhausted:
        confidence = max(0.80 - (retry_count * 0.10), 0.40)
        return (
            Intervention.PAYMENT_RETRY,
            f"Retryable failure ('{failure_raw}') with {retry_count} prior "
            f"attempt(s); within retry limit of {max_retries}.",
            confidence,
        )

    if exhausted:
        if amount >= high_value:
            return (
                Intervention.ESCALATE,
                f"Retry limit reached ({retry_count}/{max_retries}) on a "
                f"high-value payment (≥{high_value}). Manual review warranted.",
                0.85,
            )
        return (
            Intervention.ALTERNATE_PAYMENT_PROMPT,
            f"Retry limit reached ({retry_count}/{max_retries}). "
            "Prompting customer for an alternate payment method.",
            0.75,
        )

    if failure_raw in _METHOD_CHANGE_FAILURES or failure_raw in _FUND_FAILURES:
        if amount >= high_value:
            return (
                Intervention.ESCALATE,
                f"Non-retryable failure ('{failure_raw}') on a high-value "
                f"payment (≥{high_value}). Escalating for manual follow-up.",
                0.80,
            )
        return (
            Intervention.ALTERNATE_PAYMENT_PROMPT,
            f"Non-retryable failure reason: '{failure_raw}'. "
            "Alternate payment method prompt is the appropriate next step.",
            0.72,
        )

    if amount < low_value:
        return (
            Intervention.NO_ACTION,
            f"Low-value payment ({amount}) with unclear failure signal "
            f"('{failure_raw}'). Cost of intervention exceeds expected recovery.",
            0.60,
        )

    return (
        Intervention.ALTERNATE_PAYMENT_PROMPT,
        f"Unclassified failure ('{failure_raw}'). Defaulting to alternate "
        "payment prompt as safest available intervention.",
        0.50,
    )


# ===========================================================================
# Checkout abandonment rules
# ===========================================================================

def decide_checkout(case: RecoveryCase) -> tuple[Intervention, str, float]:
    """
    Checkout-abandonment decision rules.

    Uses the trained Random Forest (via app.models.checkout_recovery) as a
    propensity signal when session features are present; otherwise falls back
    to the manually supplied recovery_probability.

    The RF score is a PRIORITIZATION signal, NOT a causal intervention-lift.
    """
    ctx    = case.context
    amount = case.revenue_at_risk

    model_prob = score_checkout_case(ctx)
    if model_prob is not None:
        case.recovery_probability = model_prob

    prob = case.recovery_probability

    low_value      = THRESHOLDS["checkout_low_value"]
    high_value     = THRESHOLDS["checkout_high_value"]
    low_propensity = THRESHOLDS["checkout_low_propensity"]
    inc_min_value  = THRESHOLDS["checkout_incentive_min_value"]
    inc_min_prob   = THRESHOLDS["checkout_incentive_min_prob"]

    if ctx.get("already_recovered", False):
        return (
            Intervention.NO_ACTION,
            "Checkout has already been recovered; no further intervention needed.",
            1.0,
        )

    if ctx.get("intervention_already_sent", False):
        return (
            Intervention.NO_ACTION,
            "An intervention has already been sent for this abandoned session.",
            0.90,
        )

    if prob < low_propensity and amount < low_value:
        return (
            Intervention.NO_ACTION,
            f"Recovery propensity ({prob:.2f}) and cart value ({amount}) are "
            "both below minimum thresholds. Intervention not cost-effective.",
            0.70,
        )

    if (
        ctx.get("incentive_eligible", False)
        and amount >= inc_min_value
        and prob >= inc_min_prob
    ):
        return (
            Intervention.INCENTIVIZED_RECOVERY,
            f"Cart value ({amount}) and recovery propensity ({prob:.2f}) meet "
            "incentive thresholds, and customer is marked incentive-eligible.",
            prob,
        )

    if amount >= high_value:
        return (
            Intervention.CHECKOUT_REMINDER,
            f"High-value abandoned cart ({amount}). Reminder dispatched "
            f"regardless of propensity ({prob:.2f}).",
            max(prob, 0.55),
        )

    if prob >= THRESHOLDS["propensity_high"]:
        return (
            Intervention.CHECKOUT_REMINDER,
            f"High recovery propensity ({prob:.2f}) warrants a checkout reminder.",
            prob,
        )

    if amount >= low_value or prob >= THRESHOLDS["propensity_medium"]:
        return (
            Intervention.CHECKOUT_REMINDER,
            f"Moderate cart value ({amount}) or propensity ({prob:.2f}). "
            "Sending a low-friction checkout reminder.",
            max(prob, 0.35),
        )

    return (
        Intervention.NO_ACTION,
        f"Cart value ({amount}) and recovery propensity ({prob:.2f}) do not "
        "meet any intervention threshold.",
        0.65,
    )


# ===========================================================================
# Overdue receivable rules
# ===========================================================================

def decide_receivable(case: RecoveryCase) -> tuple[Intervention, str, float]:
    """Overdue-receivable decision rules."""
    ctx    = case.context
    amount = case.revenue_at_risk

    escalate_days   = THRESHOLDS["receivable_escalate_days"]
    high_value      = THRESHOLDS["receivable_high_value"]
    high_value_days = THRESHOLDS["receivable_high_value_days"]
    cooldown        = THRESHOLDS["receivable_reminder_cooldown"]

    status        = str(ctx.get("payment_status", "")).lower().strip()
    days_overdue  = ctx.get("days_overdue")
    is_priority   = ctx.get("is_priority_account", False)
    days_since_rem = ctx.get("days_since_last_reminder")
    customer_tier = str(ctx.get("customer_tier", "")).lower().strip()

    if status in ("paid", "settled"):
        return (
            Intervention.NO_ACTION,
            "Invoice is already paid or settled; no reminder should be sent.",
            1.0,
        )

    if is_priority:
        return (
            Intervention.ESCALATE,
            "Priority/key account with outstanding invoice. Escalating for "
            "dedicated account-management follow-up.",
            0.90,
        )

    if days_overdue is not None and days_overdue >= escalate_days:
        return (
            Intervention.ESCALATE,
            f"Invoice is {days_overdue} days overdue (threshold: {escalate_days}). "
            "Automated reminders are insufficient at this stage.",
            0.88,
        )

    if (
        amount >= high_value
        and days_overdue is not None
        and days_overdue >= high_value_days
    ):
        return (
            Intervention.ESCALATE,
            f"High-value invoice ({amount}) is {days_overdue} days overdue "
            f"(high-value escalation threshold: {high_value_days} days).",
            0.85,
        )

    if customer_tier == "enterprise" and days_overdue is not None and days_overdue >= 30:
        return (
            Intervention.ESCALATE,
            f"Enterprise-tier customer with invoice {days_overdue} days overdue. "
            "Escalating for account-manager outreach.",
            0.82,
        )

    if days_since_rem is not None and days_since_rem < cooldown:
        return (
            Intervention.NO_ACTION,
            f"A reminder was sent {days_since_rem} day(s) ago. "
            f"Cooldown period is {cooldown} days — no duplicate reminder.",
            0.85,
        )

    overdue_str = f"{days_overdue} days" if days_overdue is not None else "an unknown number of days"
    return (
        Intervention.INVOICE_REMINDER,
        f"Invoice of {amount} is {overdue_str} overdue. Sending a payment reminder.",
        0.78,
    )
