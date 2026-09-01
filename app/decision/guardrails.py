"""
Guardrail layer — safety and business constraints applied AFTER a candidate
action has been selected by a rule module.

Each check returns (passed: bool, reason: str).  The engine calls
validate_decision() which short-circuits on the first failure.
"""

from __future__ import annotations

from app.decision.schemas import CaseType, GuardrailStatus, Intervention, RecoveryCase
from app.decision._catalogue import CATALOGUE, THRESHOLDS


# ---------------------------------------------------------------------------
# Individual guardrail checks
# ---------------------------------------------------------------------------

def _check_in_catalogue(action: Intervention) -> tuple[bool, str]:
    if action not in CATALOGUE:
        return False, f"Action '{action}' is not in the permitted intervention catalogue."
    return True, ""


def _check_payment_guardrails(
    case: RecoveryCase, action: Intervention
) -> tuple[bool, str]:
    ctx = case.context

    if action == Intervention.PAYMENT_RETRY:
        if ctx.get("payment_succeeded", False):
            return False, "Payment has already succeeded; retry is not permitted."
        retry_count = ctx.get("retry_count", 0)
        if retry_count >= THRESHOLDS["payment_max_retries"]:
            return False, (
                f"Retry count ({retry_count}) has reached the maximum "
                f"({THRESHOLDS['payment_max_retries']}); retry is not permitted."
            )

    return True, ""


def _check_checkout_guardrails(
    case: RecoveryCase, action: Intervention
) -> tuple[bool, str]:
    ctx = case.context

    if ctx.get("already_recovered", False):
        if action != Intervention.NO_ACTION:
            return False, "Checkout has already been recovered; no intervention needed."

    if ctx.get("intervention_already_sent", False):
        if action not in (Intervention.NO_ACTION,):
            return False, "An intervention has already been dispatched for this session."

    if action == Intervention.INCENTIVIZED_RECOVERY:
        if not ctx.get("incentive_eligible", False):
            return False, (
                "INCENTIVIZED_RECOVERY requires explicit eligibility. "
                "Set context['incentive_eligible'] = True to unlock."
            )

    return True, ""


def _check_receivable_guardrails(
    case: RecoveryCase, action: Intervention
) -> tuple[bool, str]:
    ctx = case.context

    if ctx.get("payment_status", "").lower() in ("paid", "settled"):
        if action not in (Intervention.NO_ACTION,):
            return False, "Invoice is already paid; no reminder should be sent."

    if action == Intervention.INVOICE_REMINDER:
        days_since = ctx.get("days_since_last_reminder")
        if days_since is not None and days_since < THRESHOLDS["receivable_reminder_cooldown"]:
            return False, (
                f"Last reminder was sent {days_since} day(s) ago — "
                f"cooldown is {THRESHOLDS['receivable_reminder_cooldown']} days."
            )

    return True, ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_decision(
    case: RecoveryCase, action: Intervention
) -> tuple[GuardrailStatus, str]:
    """
    Run all applicable guardrails for the given case and proposed action.

    Returns
    -------
    (GuardrailStatus.APPROVED, "")          — all checks passed
    (GuardrailStatus.BLOCKED, reason_str)   — first failed check
    """
    checks = [_check_in_catalogue(action)]

    if case.case_type == CaseType.PAYMENT_FAILURE:
        checks.append(_check_payment_guardrails(case, action))
    elif case.case_type == CaseType.CHECKOUT_ABANDONMENT:
        checks.append(_check_checkout_guardrails(case, action))
    elif case.case_type == CaseType.OVERDUE_RECEIVABLE:
        checks.append(_check_receivable_guardrails(case, action))

    for passed, reason in checks:
        if not passed:
            return GuardrailStatus.BLOCKED, reason

    return GuardrailStatus.APPROVED, ""
