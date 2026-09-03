"""Scan prepared revenue-risk sources and evaluate their recovery cases."""

from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from app.config.settings import (
    PREPARED_DATA_DIR,
    PROCESSED_CHECKOUT_DIR,
    PROCESSED_PAYMENT_DIR,
    PROCESSED_RECEIVABLES_DIR,
    RAW_PAYMENT_DIR,
)
from app.decision import engine as decision_engine
from app.decision.schemas import CaseType, DecisionResult, RecoveryCase
from app.models.checkout_recovery import score_checkout_cases
from app.services.o2c_adapter import build_o2c_case


_latest_scan: RevenueScanResult | None = None
_latest_cases: dict[str, RecoveryCase] = {}


@dataclass
class RevenueScanResult:
    scan_id: str
    cases: list[DecisionResult]
    total_revenue_at_risk: float

    @property
    def cases_detected(self) -> int:
        return len(self.cases)

    @property
    def actions_recommended(self) -> int:
        return sum(result.recommended_action.value != "NO_ACTION" for result in self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "cases_detected": self.cases_detected,
            "total_revenue_at_risk": round(self.total_revenue_at_risk, 2),
            "actions_recommended": self.actions_recommended,
            "cases": [result.to_dict() for result in self.cases],
        }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _find_source(
    directories: tuple[Path, ...],
    preferred_names: tuple[str, ...],
    required_columns: set[str] | tuple[set[str], ...],
) -> Path | None:
    """Find a prepared source by name or schema, never by arbitrary raw data."""
    candidates = [
        path
        for directory in directories
        if directory.exists()
        for path in sorted(directory.rglob("*.csv"))
    ]
    required_groups = (
        (required_columns,)
        if isinstance(required_columns, set)
        else required_columns
    )
    for path in candidates:
        if path.name in preferred_names:
            return path
    for path in candidates:
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                columns = set(next(csv.reader(handle), []))
        except (OSError, UnicodeError, csv.Error):
            continue
        if any(group <= columns for group in required_groups):
            return path
    return None


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _checkout_cases(path: Path | None) -> Iterable[RecoveryCase]:
    if path is None:
        return
    prepared_cases = []
    for row in _read_csv(path):
        is_prepared = "session_start_ts" in row and "session_end_ts" in row
        abandoned = _as_bool(row.get("abandoned", ""))
        has_cart = _as_float(row.get("cart_additions")) > 0
        has_transaction = _as_float(row.get("transactions")) > 0
        if not is_prepared and not (abandoned or (has_cart and not has_transaction)):
            continue
        context = {
            key: _as_float(row[key])
            for key in (
                "cart_additions", "views", "unique_products", "event_count",
                "duration_minutes", "hour_of_day", "day_of_week",
            )
            if row.get(key, "") != ""
        }
        if "hour_of_day" not in context or "day_of_week" not in context:
            timestamp = row.get("abandoned_at") or row.get("session_end") or row.get("session_end_ts")
            if timestamp:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                context.setdefault("hour_of_day", parsed.hour)
                context.setdefault("day_of_week", parsed.weekday())
        decision_context = {
            key: value
            for key, value in context.items()
            if key not in {
                "cart_additions", "views", "unique_products", "event_count",
                "duration_minutes", "hour_of_day", "day_of_week",
            }
        }
        session_id = row.get("session_id") or row.get("checkout_id")
        visitor_id = row.get("visitorid") or row.get("customer_id") or "unknown"
        if not session_id:
            continue
        prepared_cases.append((row, context, decision_context, session_id, visitor_id))
    probabilities = score_checkout_cases([item[1] for item in prepared_cases])
    if probabilities is None:
        return
    for (row, _context, decision_context, session_id, visitor_id), probability in zip(prepared_cases, probabilities):
        yield RecoveryCase(
            case_id=f"checkout_{session_id}",
            case_type=CaseType.CHECKOUT_ABANDONMENT,
            customer_id=str(visitor_id),
            revenue_at_risk=_as_float(row.get("revenue_at_risk", row.get("cart_value"))),
            recovery_probability=probability,
            context=decision_context,
        )


def _payment_cases(path: Path | None) -> Iterable[RecoveryCase]:
    if path is None:
        return
    for row in _read_csv(path):
        status = str(row.get("payment_status", row.get("status", "failed"))).lower()
        if status not in {"failed", "failure", "declined", "error"}:
            continue
        source_id = row.get("payment_id") or row.get("transaction_id") or row.get("id")
        if not source_id:
            continue
        yield RecoveryCase(
            case_id=f"payment_{source_id}",
            case_type=CaseType.PAYMENT_FAILURE,
            customer_id=str(row.get("customer_id", row.get("cust_number", "unknown"))),
            revenue_at_risk=_as_float(row.get("revenue_at_risk", row.get("amount"))),
            context={
                "failure_reason": row.get("failure_reason", row.get("error_code", "")),
                "retry_count": int(_as_float(row.get("retry_count"))),
                "payment_succeeded": False,
            },
        )


def _o2c_cases(path: Path | None, observation_cutoff: date | None) -> Iterable[RecoveryCase]:
    if path is None:
        return
    rows = _read_csv(path)
    dates = [datetime.fromisoformat(row["due_date"]).date() for row in rows if row.get("due_date")]
    cutoff = observation_cutoff or max(dates, default=date.today())
    for row in rows:
        if str(row.get("record_type", "open")).lower() != "open" or not _as_bool(row.get("isOpen", "1")):
            continue
        due_date = datetime.fromisoformat(row["due_date"]).date()
        days_overdue = (cutoff - due_date).days
        if days_overdue <= 0:
            continue
        row = dict(row)
        row["days_overdue"] = days_overdue
        row["customer_tier"] = row.get("customer_tier", row.get("risk_tier", "standard"))
        row["is_priority_account"] = row.get("is_priority_account", "false")
        row["days_since_last_reminder"] = row.get("days_since_last_reminder") or None
        yield build_o2c_case(row)


def scan_revenue_risk(
    *,
    checkout_path: Path | None = None,
    payment_path: Path | None = None,
    o2c_path: Path | None = None,
    observation_cutoff: date | None = None,
    max_cases: int = 100,
) -> RevenueScanResult:
    """Evaluate available prepared candidates and return a bounded work queue."""
    checkout_path = checkout_path or _find_source(
        (PREPARED_DATA_DIR, PROCESSED_CHECKOUT_DIR),
        ("prepared_checkout_sessions.csv", "sessions.csv", "checkout_sessions.csv", "checkout_features.csv"),
        ({"session_id", "cart_additions", "event_count", "session_start_ts", "session_end_ts"},
         {"session_id", "cart_additions", "event_count"}),
    )
    payment_path = payment_path or _find_source(
        (PROCESSED_PAYMENT_DIR, RAW_PAYMENT_DIR),
        ("payments.csv", "payment_failures.csv", "transactions.csv"),
        ({"status", "payment_id"}, {"payment_status", "payment_id"},
         {"status", "transaction_id"}, {"payment_status", "transaction_id"},
         {"status", "id"}, {"payment_status", "id"}),
    )
    o2c_path = o2c_path or PROCESSED_RECEIVABLES_DIR / "o2c_scored_open_invoices.csv"
    checkout_path = checkout_path if checkout_path and checkout_path.exists() else None
    payment_path = payment_path if payment_path and payment_path.exists() else None
    o2c_path = o2c_path if o2c_path.exists() else None

    cases = list(_payment_cases(payment_path))
    cases.extend(_checkout_cases(checkout_path))
    cases.extend(_o2c_cases(o2c_path, observation_cutoff))
    unique_cases = {case.case_id: case for case in cases}
    evaluated = [decision_engine.decide(case) for case in unique_cases.values()]
    evaluated.sort(key=lambda result: ({"HIGH": 3, "MEDIUM": 2, "LOW": 1}[result.priority.value], result.revenue_at_risk), reverse=True)
    selected_ids: set[str] = set()
    queue: list[DecisionResult] = []
    for case_type in CaseType:
        representative = next((result for result in evaluated if result.case_type == case_type), None)
        if representative is not None and len(queue) < max_cases:
            queue.append(representative)
            selected_ids.add(representative.case_id)
    queue.extend(
        result
        for result in evaluated
        if result.case_id not in selected_ids and len(queue) < max_cases
    )
    result = RevenueScanResult(
        scan_id=f"scan_{uuid.uuid4().hex[:16]}",
        cases=queue,
        total_revenue_at_risk=sum(result.revenue_at_risk for result in queue),
    )
    global _latest_scan, _latest_cases
    _latest_scan = result
    _latest_cases = {case.case_id: unique_cases[case.case_id] for case in queue}
    return result


def get_latest_scan() -> RevenueScanResult | None:
    """Return the current in-memory work queue, if a scan has run."""
    return _latest_scan


def get_case(case_id: str) -> RecoveryCase | None:
    """Return the original case for a case-ID execution request."""
    return _latest_cases.get(case_id)
