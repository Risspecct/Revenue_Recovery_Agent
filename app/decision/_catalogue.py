"""
Intervention catalogue and configurable thresholds.

Internal module — import THRESHOLDS and CATALOGUE from here.
All magic numbers live here; never scatter raw literals through rule logic.
"""

from __future__ import annotations

from app.decision.schemas import Intervention

# Full intervention catalogue — the engine must NEVER produce an action
# that is not in this set.
CATALOGUE: frozenset[Intervention] = frozenset(Intervention)

# Configurable thresholds — edit here to tune without touching rule code.
THRESHOLDS: dict = {

    # Priority classification
    "revenue_high":   5_000.0,
    "revenue_medium": 1_000.0,

    "propensity_high":   0.60,
    "propensity_medium": 0.30,

    "risk_score_high":   0.60,
    "risk_score_medium": 0.30,

    # Payment-failure rules
    "payment_max_retries": 3,
    "payment_high_value":  5_000.0,
    "payment_low_value":     500.0,

    # Checkout-abandonment rules
    "checkout_high_value":          3_000.0,
    "checkout_low_value":             300.0,
    "checkout_low_propensity":         0.20,
    "checkout_incentive_min_value":  1_000.0,
    "checkout_incentive_min_prob":     0.40,

    # Overdue-receivable rules
    "receivable_high_value":       10_000.0,
    "receivable_escalate_days":        60,
    "receivable_high_value_days":      30,
    "receivable_reminder_cooldown":     7,

    # Payment — empty/missing failure_reason handling.
    # When True, a payment with no failure_reason is treated as retryable
    # (optimistic retry assumption). Set to False to treat unknown failures
    # as non-retryable instead.
    "empty_failure_reason_retryable": True,
}
