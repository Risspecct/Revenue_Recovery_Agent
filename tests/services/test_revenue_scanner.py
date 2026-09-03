from __future__ import annotations

import csv
from datetime import date

from app.services import revenue_scanner


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_scan_unifies_domains_and_keeps_stable_ids(tmp_path, monkeypatch):
    payment = tmp_path / "payments.csv"
    checkout = tmp_path / "sessions.csv"
    o2c = tmp_path / "o2c.csv"
    _write_csv(payment, [{
        "payment_id": "p-1", "status": "failed", "customer_id": "cust-p",
        "amount": "1200", "failure_reason": "timeout", "retry_count": "0",
    }])
    _write_csv(checkout, [{
        "session_id": "s-1", "visitorid": "cust-c", "abandoned": "true",
        "cart_additions": "2", "views": "5", "unique_products": "2",
        "event_count": "7", "duration_minutes": "3", "hour_of_day": "12",
        "day_of_week": "2", "revenue_at_risk": "2500",
    }])
    _write_csv(o2c, [{
        "invoice_id": "i-1", "cust_number": "cust-r", "due_date": "2020-01-01",
        "record_type": "open", "isOpen": "1", "total_open_amount": "3000",
        "late_payment_probability": "0.9", "risk_tier": "HIGH",
    }])
    monkeypatch.setattr(revenue_scanner, "score_checkout_cases", lambda contexts: [0.72] * len(contexts))

    result = revenue_scanner.scan_revenue_risk(
        payment_path=payment,
        checkout_path=checkout,
        o2c_path=o2c,
        observation_cutoff=date(2020, 1, 15),
    )

    assert {case.case_type.value for case in result.cases} == {
        "PAYMENT_FAILURE", "CHECKOUT_ABANDONMENT", "OVERDUE_RECEIVABLE",
    }
    assert {case.case_id for case in result.cases} == {
        "payment_p-1", "checkout_s-1", "o2c_i-1",
    }
    assert result.total_revenue_at_risk == 6700.0
    assert result.actions_recommended == 3
    again = revenue_scanner.scan_revenue_risk(
        payment_path=payment, checkout_path=checkout, o2c_path=o2c,
        observation_cutoff=date(2020, 1, 15),
    )
    assert {case.case_id for case in again.cases} == {case.case_id for case in result.cases}


def test_scan_uses_engine_outputs_and_domain_probabilities(tmp_path, monkeypatch):
    checkout = tmp_path / "sessions.csv"
    o2c = tmp_path / "o2c.csv"
    _write_csv(checkout, [{
        "session_id": "s-2", "visitorid": "cust-c", "abandoned": "true",
        "cart_additions": "2", "views": "5", "unique_products": "2",
        "event_count": "7", "duration_minutes": "3", "hour_of_day": "12",
        "day_of_week": "2", "revenue_at_risk": "2500",
    }])
    _write_csv(o2c, [{
        "invoice_id": "i-2", "cust_number": "cust-r", "due_date": "2020-01-01",
        "record_type": "open", "isOpen": "1", "total_open_amount": "3000",
        "late_payment_probability": "0.9", "risk_tier": "HIGH",
    }])
    monkeypatch.setattr(revenue_scanner, "score_checkout_cases", lambda contexts: [0.72] * len(contexts))

    result = revenue_scanner.scan_revenue_risk(
        checkout_path=checkout, o2c_path=o2c,
        observation_cutoff=date(2020, 1, 15),
    )
    by_type = {case.case_type.value: case for case in result.cases}
    assert by_type["CHECKOUT_ABANDONMENT"].recovery_probability == 0.72
    assert by_type["OVERDUE_RECEIVABLE"].recovery_probability == 0.0
    assert by_type["OVERDUE_RECEIVABLE"].risk_score > 0
    assert by_type["OVERDUE_RECEIVABLE"].guardrail_status.value == "APPROVED"


def test_scan_discovers_prepared_sources_without_raw_checkout_fallback(tmp_path, monkeypatch):
    checkout_dir = tmp_path / "checkout"
    payment_dir = tmp_path / "payment"
    checkout_dir.mkdir()
    payment_dir.mkdir()
    _write_csv(checkout_dir / "prepared_sessions.csv", [{
        "session_id": "discovered", "visitorid": "cust-c", "abandoned": "1",
        "cart_additions": "1", "views": "2", "unique_products": "1",
        "event_count": "3", "duration_minutes": "1", "hour_of_day": "10",
        "day_of_week": "1", "revenue_at_risk": "900",
    }])
    _write_csv(payment_dir / "failed_transactions.csv", [{
        "transaction_id": "discovered", "payment_status": "failed",
        "customer_id": "cust-p", "amount": "800", "failure_reason": "timeout",
    }])
    monkeypatch.setattr(revenue_scanner, "PROCESSED_CHECKOUT_DIR", checkout_dir)
    monkeypatch.setattr(revenue_scanner, "PROCESSED_PAYMENT_DIR", payment_dir)
    monkeypatch.setattr(revenue_scanner, "RAW_PAYMENT_DIR", tmp_path / "missing-payment")
    monkeypatch.setattr(revenue_scanner, "score_checkout_cases", lambda contexts: [0.8] * len(contexts))

    result = revenue_scanner.scan_revenue_risk(o2c_path=tmp_path / "missing-o2c.csv")

    assert {case.case_id for case in result.cases} == {
        "payment_discovered", "checkout_discovered",
    }


def test_scan_does_not_fabricate_missing_sources(tmp_path):
    result = revenue_scanner.scan_revenue_risk(
        checkout_path=tmp_path / "missing-checkout.csv",
        payment_path=tmp_path / "missing-payment.csv",
        o2c_path=tmp_path / "missing-o2c.csv",
    )
    assert result.cases == []
    assert result.total_revenue_at_risk == 0.0


def test_scan_uses_exact_prepared_checkout_source_without_revenue_fabrication(tmp_path, monkeypatch):
    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir()
    _write_csv(prepared_dir / "prepared_checkout_sessions.csv", [{
        "session_id": "42", "visitorid": "visitor-7",
        "session_start_ts": "2015-09-01T10:00:00",
        "session_end_ts": "2015-09-01T10:05:00",
        "cart_additions": "2", "views": "5", "unique_products": "2",
        "event_count": "7", "duration_minutes": "5", "hour_of_day": "10",
        "day_of_week": "1",
    }])
    seen = []

    def score(context):
        seen.append(context)
        return 0.61

    monkeypatch.setattr(revenue_scanner, "PREPARED_DATA_DIR", prepared_dir)
    monkeypatch.setattr(revenue_scanner, "PROCESSED_CHECKOUT_DIR", tmp_path / "empty-processed")
    monkeypatch.setattr(revenue_scanner, "score_checkout_cases", lambda contexts: [score(context) for context in contexts])

    result = revenue_scanner.scan_revenue_risk(
        payment_path=tmp_path / "missing-payment.csv",
        o2c_path=tmp_path / "missing-o2c.csv",
    )

    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.case_id == "checkout_42"
    assert case.revenue_at_risk == 0.0
    assert case.recovery_probability == 0.61
    assert set(seen[0]) == {
        "cart_additions", "views", "unique_products", "event_count",
        "duration_minutes", "hour_of_day", "day_of_week",
    }
