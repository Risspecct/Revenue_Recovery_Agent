from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from app.config.settings import (
    EVENTS_CSV,
    PREPARED_DATA_DIR,
    PROCESSED_CHECKOUT_DIR,
)


@dataclass
class BatchRecoveryResult:
    cases_evaluated: int
    interventions_recommended: int
    known_outcomes: int
    recovered_cases: int
    revenue_at_risk: float
    recovered_revenue: float

    @property
    def recovery_rate(self) -> float:
        if self.known_outcomes == 0:
            return 0.0

        return self.recovered_cases / self.known_outcomes

    def to_dict(self) -> dict[str, Any]:
        return {
            "cases_evaluated": self.cases_evaluated,
            "interventions_recommended": self.interventions_recommended,
            "known_outcomes": self.known_outcomes,
            "recovered_cases": self.recovered_cases,
            "revenue_at_risk": round(self.revenue_at_risk, 2),
            "recovered_revenue": round(self.recovered_revenue, 2),
            "recovery_rate": round(self.recovery_rate, 4),
        }


def _get_context(case: Any) -> dict[str, Any]:
    if isinstance(case, dict):
        return case.get("context", {}) or {}

    return getattr(case, "context", {}) or {}


def _get_revenue(case: Any) -> float:
    if isinstance(case, dict):
        value = case.get("revenue_at_risk", 0)
    else:
        value = getattr(case, "revenue_at_risk", 0)

    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _find_checkout_source() -> tuple[Any, Any]:
    """
    Locate the prepared checkout sessions and raw RetailRocket events
    using the application's centralized dataset paths.
    """
    prepared_candidates = [
        PROCESSED_CHECKOUT_DIR / "prepared_checkout_sessions.csv",
        PREPARED_DATA_DIR / "prepared_checkout_sessions.csv",
    ]

    prepared_path = next(
        (path for path in prepared_candidates if path.exists()),
        None,
    )

    if prepared_path is None or not EVENTS_CSV.exists():
        return None, None

    return prepared_path, EVENTS_CSV


def reconstruct_checkout_outcomes() -> dict[str, bool]:
    """
    Reconstruct the exact historical checkout target used by the
    checkout-recovery model.

    Rules:
      - use prepared abandoned sessions
      - transaction must occur after abandonment
      - transaction must occur within 7 days
      - transaction is assigned to the closest preceding abandoned session
      - each transaction can recover only one session
      - each abandoned session can recover only once

    Returns:
        Mapping of session_id -> historically recovered.
    """
    prepared_path, events_path = _find_checkout_source()

    if prepared_path is None or events_path is None:
        return {}

    sessions = pd.read_csv(prepared_path)
    events = pd.read_csv(events_path)

    required_session_columns = {
        "session_id",
        "visitorid",
        "session_end_ts",
    }

    required_event_columns = {
        "timestamp",
        "visitorid",
        "event",
    }

    if not required_session_columns.issubset(sessions.columns):
        return {}

    if not required_event_columns.issubset(events.columns):
        return {}

    # RetailRocket timestamps are Unix milliseconds.
    sessions["abandoned_at"] = pd.to_datetime(
        sessions["session_end_ts"],
        unit="ms",
        errors="coerce",
    )

    transactions = events[
        events["event"].astype(str).str.lower().eq("transaction")
    ][["visitorid", "timestamp"]].copy()

    transactions["transaction_time"] = pd.to_datetime(
        transactions["timestamp"],
        unit="ms",
        errors="coerce",
    )

    sessions = sessions.dropna(
        subset=["visitorid", "abandoned_at"]
    ).copy()

    transactions = transactions.dropna(
        subset=["visitorid", "transaction_time"]
    ).copy()

    # The prepared dataset already represents the full-observation
    # checkout cohort. Keep the explicit 7-day rule here as well.
    if sessions.empty or transactions.empty:
        return {
            str(session_id): False
            for session_id in sessions["session_id"]
        }

    # Match transactions to abandoned sessions belonging to the
    # same visitor.
    candidates = sessions[
        ["session_id", "visitorid", "abandoned_at"]
    ].merge(
        transactions[
            ["visitorid", "transaction_time"]
        ],
        on="visitorid",
        how="inner",
    )

    candidates["days_after_abandonment"] = (
        candidates["transaction_time"]
        - candidates["abandoned_at"]
    ).dt.total_seconds() / 86400.0

    candidates = candidates[
        (candidates["days_after_abandonment"] > 0)
        & (candidates["days_after_abandonment"] <= 7)
    ].copy()

    if candidates.empty:
        return {
            str(session_id): False
            for session_id in sessions["session_id"]
        }

    # Exact notebook rule:
    # each transaction belongs to the closest preceding
    # abandoned session.
    candidates["distance"] = candidates["days_after_abandonment"]

    candidates = candidates.sort_values(
        [
            "visitorid",
            "transaction_time",
            "distance",
        ]
    )

    candidates = candidates.drop_duplicates(
        subset=["visitorid", "transaction_time"],
        keep="first",
    )

    # One abandoned session can only be recovered once.
    candidates = candidates.sort_values(
        ["visitorid", "session_id", "transaction_time"]
    )

    candidates = candidates.drop_duplicates(
        subset=["session_id"],
        keep="first",
    )

    recovered_ids = set(
        candidates["session_id"].astype(str)
    )

    return {
        str(session_id): str(session_id) in recovered_ids
        for session_id in sessions["session_id"]
    }


def calculate_batch_recovery(
    decisions: Iterable[Any],
    original_cases: dict[str, Any],
) -> BatchRecoveryResult:
    """
    Calculate historical replay recovery metrics.

    Historical recovery is reported only when the source data
    actually contains a recoverable historical outcome.

    This does NOT claim that our simulated intervention caused
    the historical recovery.
    """

    decisions = list(decisions)

    checkout_outcomes = reconstruct_checkout_outcomes()

    cases_evaluated = len(decisions)
    interventions_recommended = 0
    known_outcomes = 0
    recovered_cases = 0

    revenue_at_risk = 0.0
    recovered_revenue = 0.0

    for decision in decisions:
        case_id = decision.case_id
        original_case = original_cases.get(case_id)

        if original_case is None:
            continue

        revenue = _get_revenue(original_case)
        revenue_at_risk += revenue

        action = decision.recommended_action.value

        if action != "NO_ACTION":
            interventions_recommended += 1

        context = _get_context(original_case)

        outcome = context.get("recovered_within_7d")

        # For checkout cases, reconstruct the historical target
        # directly from the original RetailRocket event stream.
        if outcome is None and case_id.startswith("checkout_"):
            session_id = case_id[len("checkout_"):]
            outcome = checkout_outcomes.get(session_id)

        if outcome is None:
            outcome = context.get("historically_recovered")

        if outcome is None:
            continue

        known_outcomes += 1

        if bool(outcome):
            recovered_cases += 1

            # Only count recovered revenue when the source actually
            # contains a monetary value.
            if revenue > 0:
                recovered_revenue += revenue

    return BatchRecoveryResult(
        cases_evaluated=cases_evaluated,
        interventions_recommended=interventions_recommended,
        known_outcomes=known_outcomes,
        recovered_cases=recovered_cases,
        revenue_at_risk=revenue_at_risk,
        recovered_revenue=recovered_revenue,
    )
