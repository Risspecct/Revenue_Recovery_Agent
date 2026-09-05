"""
Bounded execution layer.

The executor translates an approved DecisionResult into a deterministic
simulated recovery action.

Core constraint
---------------
The executor NEVER makes its own recovery decision.
It may only execute actions that are present in the approved DecisionResult.

Simulation contract
-------------------
Every execution is a simulation.  simulated=True is always set.
The executor never claims that:
  - a payment was actually processed;
  - an invoice was paid;
  - a customer definitely recovered;
  - revenue was definitely recovered.
It simulates that the recovery action was initiated / queued / escalated.

Guardrail enforcement
---------------------
If guardrail_status == BLOCKED the executor returns REJECTED and does nothing.
If the action is not in the supported catalogue the executor returns REJECTED.
"""

from __future__ import annotations

from app.decision._catalogue import CATALOGUE
from app.decision.schemas import (
    DecisionResult,
    ExecutionResult,
    ExecutionStatus,
    GuardrailStatus,
    Intervention,
)

# ---------------------------------------------------------------------------
# Action → simulated message map
# The messages describe what was initiated/queued, not what succeeded.
# ---------------------------------------------------------------------------

_ACTION_MESSAGES: dict[Intervention, str] = {
    Intervention.PAYMENT_RETRY: "Payment retry initiated.",
    Intervention.ALTERNATE_PAYMENT_PROMPT: "Alternate payment method flow initiated.",
    Intervention.CHECKOUT_REMINDER: "Checkout recovery reminder queued.",
    Intervention.INCENTIVIZED_RECOVERY: "Eligible recovery incentive issued.",
    Intervention.INVOICE_REMINDER: "Invoice reminder queued.",
    Intervention.ESCALATE: "Recovery case escalated for manual review.",
    Intervention.NO_ACTION: "No recovery action taken.",
}


def execute(decision: DecisionResult) -> ExecutionResult:
    """
    Execute the bounded recovery action contained in an approved DecisionResult.

    Parameters
    ----------
    decision : DecisionResult
        The decision produced by the recovery decision engine.

    Returns
    -------
    ExecutionResult
        Always returned — never raises on bad input; malformed/blocked
        decisions are rejected with status=REJECTED.

    Rules
    -----
    - BLOCKED guardrail_status  → REJECTED (executor refuses to act)
    - Action not in catalogue   → REJECTED (executor refuses to act)
    - NO_ACTION                 → SKIPPED  (no intervention warranted)
    - ESCALATE (ESCALATED)      → EXECUTED (bounded escalation simulated)
    - Any other approved action → EXECUTED (action simulated)
    """
    exec_id = ExecutionResult.make_id()
    timestamp = ExecutionResult.utc_now()

    if decision is None or not hasattr(decision, "case_id"):
        return ExecutionResult(
            execution_id=exec_id,
            case_id="unknown",
            action=Intervention.NO_ACTION,
            status=ExecutionStatus.REJECTED,
            message="Execution rejected: malformed decision result received.",
            simulated=True,
            timestamp=timestamp,
        )

    action = getattr(decision, "recommended_action", None)
    guardrail_status = getattr(decision, "guardrail_status", None)
    case_id = getattr(decision, "case_id", "unknown")

    # --- Guard: blocked decision ------------------------------------------
    if guardrail_status == GuardrailStatus.BLOCKED:
        return ExecutionResult(
            execution_id=exec_id,
            case_id=case_id,
            action=action if isinstance(action, Intervention) else Intervention.NO_ACTION,
            status=ExecutionStatus.REJECTED,
            message=(
                "Execution rejected: the decision was blocked by guardrails "
                "and cannot be executed."
            ),
            simulated=True,
            timestamp=timestamp,
        )

    # --- Guard: action not in supported catalogue -------------------------
    if not isinstance(action, Intervention) or action not in CATALOGUE:
        return ExecutionResult(
            execution_id=exec_id,
            case_id=case_id,
            action=action if isinstance(action, Intervention) else Intervention.NO_ACTION,
            status=ExecutionStatus.REJECTED,
            message=(
                f"Execution rejected: action '{action}' is not in the supported "
                "intervention catalogue."
            ),
            simulated=True,
            timestamp=timestamp,
        )

    # --- NO_ACTION → SKIPPED ----------------------------------------------
    if action == Intervention.NO_ACTION:
        return ExecutionResult(
            execution_id=exec_id,
            case_id=case_id,
            action=Intervention.NO_ACTION,
            status=ExecutionStatus.SKIPPED,
            message=_ACTION_MESSAGES[Intervention.NO_ACTION],
            simulated=True,
            timestamp=timestamp,
        )

    # --- All other approved actions → EXECUTED ----------------------------
    message = _ACTION_MESSAGES.get(
        action,
        f"Action '{action.value}' executed.",
    )
    return ExecutionResult(
        execution_id=exec_id,
        case_id=case_id,
        action=action,
        status=ExecutionStatus.EXECUTED,
        message=message,
        simulated=True,
        timestamp=timestamp,
    )
