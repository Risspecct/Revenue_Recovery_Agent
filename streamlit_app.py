from __future__ import annotations

import math
import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from html import escape
from typing import Any
from urllib import error, request
import json

import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DETAILS_EXECUTOR = ThreadPoolExecutor(max_workers=2)
PAGE_SIZE_OPTIONS = [6, 10, 25, 50]
PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
CASE_TYPE_LABELS = {
    "OVERDUE_RECEIVABLE": "Overdue Receivable",
    "CHECKOUT_ABANDONMENT": "Checkout Abandonment",
    "PAYMENT_FAILURE": "Payment Failure",
}


def init_state() -> None:
    st.session_state.setdefault("latest_payload", None)
    st.session_state.setdefault("latest_cases", [])
    st.session_state.setdefault("latest_error", None)
    st.session_state.setdefault("selected_case_id", None)
    st.session_state.setdefault("drawer_view", "decision")
    st.session_state.setdefault("latest_execution", None)
    st.session_state.setdefault("latest_execution_error", None)
    st.session_state.setdefault("case_details_loading", False)
    st.session_state.setdefault("case_details_error", None)
    st.session_state.setdefault("case_details_future", None)
    st.session_state.setdefault("last_frontend_refresh", None)
    st.session_state.setdefault("queue_page", 1)
    st.session_state.setdefault("queue_page_size", 6)


def api_request(path: str, method: str = "GET") -> tuple[dict[str, Any] | None, str | None]:
    endpoint = f"{API_BASE_URL}{path}"
    req = request.Request(
        endpoint,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload, None
    except error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = body.get("detail", f"HTTP {exc.code}")
        except Exception:
            detail = f"HTTP {exc.code}"
        return None, detail
    except error.URLError:
        return None, "Unable to reach the recovery service."
    except json.JSONDecodeError:
        return None, "The recovery service returned malformed data."
    except Exception:
        return None, "The frontend could not complete the API request."


def normalize_scan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required_fields = {
        "scan_id",
        "cases_detected",
        "total_revenue_at_risk",
        "actions_recommended",
        "cases",
    }
    if not isinstance(payload, dict) or not required_fields.issubset(payload):
        raise ValueError("The backend response is missing one or more expected scan fields.")
    if not isinstance(payload["cases"], list):
        raise ValueError("The backend response field 'cases' is not a list.")

    cases: list[dict[str, Any]] = []
    case_required = {
        "case_id",
        "case_type",
        "revenue_at_risk",
        "recovery_probability",
        "risk_score",
        "priority",
        "recommended_action",
        "reason",
        "confidence",
        "guardrail_status",
        "revenue_reasoning",
    }
    for raw_case in payload["cases"]:
        if not isinstance(raw_case, dict) or not case_required.issubset(raw_case):
            raise ValueError("One or more recovery cases are missing expected fields.")
        cases.append(raw_case)

    return {
        "scan_id": str(payload["scan_id"]),
        "cases_detected": int(payload["cases_detected"]),
        "total_revenue_at_risk": float(payload["total_revenue_at_risk"]),
        "actions_recommended": int(payload["actions_recommended"]),
        "cases": cases,
    }


def refresh_cases() -> str | None:
    payload, api_error = api_request("/api/recovery/cases")
    if api_error:
        st.session_state.latest_error = api_error
        return api_error
    try:
        normalized = normalize_scan_payload(payload or {})
    except ValueError as exc:
        st.session_state.latest_error = str(exc)
        return str(exc)

    st.session_state.latest_payload = normalized
    st.session_state.latest_cases = normalized["cases"]
    st.session_state.last_frontend_refresh = datetime.now()
    st.session_state.latest_error = None
    st.session_state.queue_page = 1
    return None


def run_scan() -> str | None:
    payload, api_error = api_request("/api/recovery/scan", method="POST")
    if api_error:
        st.session_state.latest_error = api_error
        return api_error
    try:
        normalized = normalize_scan_payload(payload or {})
    except ValueError as exc:
        st.session_state.latest_error = str(exc)
        return str(exc)

    st.session_state.latest_payload = normalized
    st.session_state.latest_cases = normalized["cases"]
    st.session_state.last_frontend_refresh = datetime.now()
    st.session_state.latest_error = None
    st.session_state.latest_execution = None
    st.session_state.latest_execution_error = None
    st.session_state.queue_page = 1
    return None


def fetch_case_details() -> tuple[dict[str, Any] | None, str | None]:
    payload, api_error = api_request("/api/recovery/cases")
    if api_error:
        return None, api_error
    try:
        return normalize_scan_payload(payload or {}), None
    except ValueError as exc:
        return None, str(exc)


def start_case_details_load() -> None:
    st.session_state.case_details_loading = True
    st.session_state.case_details_error = None
    st.session_state.case_details_future = DETAILS_EXECUTOR.submit(fetch_case_details)


def execute_case(case_id: str) -> str | None:
    payload, api_error = api_request(f"/api/recovery/execute/{case_id}", method="POST")
    if api_error:
        st.session_state.latest_execution_error = api_error
        return api_error

    if not isinstance(payload, dict) or "decision" not in payload or "execution" not in payload:
        message = "The backend execution response was malformed."
        st.session_state.latest_execution_error = message
        return message

    st.session_state.latest_execution = payload
    st.session_state.latest_execution_error = None
    st.session_state.drawer_view = "execution"
    return None


def format_inr(value: float) -> str:
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head = whole[-3:]
        tail = whole[:-3]
        groups = []
        while len(tail) > 2:
            groups.append(tail[-2:])
            tail = tail[:-2]
        if tail:
            groups.append(tail)
        whole = ",".join(reversed(groups)) + "," + head
    return f"{sign}₹{whole}.{frac}"


def format_type(case_type: str) -> str:
    return CASE_TYPE_LABELS.get(case_type, case_type.replace("_", " ").title())


def format_action(value: str) -> str:
    return value.replace("_", " ").title()


def find_selected_case() -> dict[str, Any] | None:
    case_id = st.session_state.selected_case_id
    if not case_id:
        return None
    return next((case for case in st.session_state.latest_cases if case["case_id"] == case_id), None)


def close_drawer() -> None:
    st.session_state.selected_case_id = None
    st.session_state.drawer_view = "decision"
    st.session_state.latest_execution = None
    st.session_state.latest_execution_error = None
    st.session_state.case_details_loading = False
    st.session_state.case_details_error = None
    st.session_state.case_details_future = None


def render_drawer_backdrop() -> None:
    st.markdown("<div class='drawer-backdrop' aria-hidden='true'></div>", unsafe_allow_html=True)
    if st.button("Close drawer", key="drawer_backdrop_close"):
        close_drawer()
        st.rerun()


def format_last_scanned() -> str:
    refreshed_at = st.session_state.last_frontend_refresh
    payload = st.session_state.latest_payload
    if refreshed_at is None or payload is None:
        return "Last scanned: Not available yet"
    ui_stamp = refreshed_at.strftime("%b %d, %Y %I:%M:%S %p")
    return f"Last scanned: UI refreshed {ui_stamp}"


def source_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "OVERDUE_RECEIVABLE": 0,
        "CHECKOUT_ABANDONMENT": 0,
        "PAYMENT_FAILURE": 0,
    }
    for case in cases:
        case_type = case.get("case_type")
        if case_type in counts:
            counts[case_type] += 1
    return counts


def priority_badge(priority: str) -> str:
    mapping = {
        "HIGH": ("#fef2f2", "#b91c1c", "#fecaca"),
        "MEDIUM": ("#fff7ed", "#c2410c", "#fed7aa"),
        "LOW": ("#f8fafc", "#475569", "#cbd5e1"),
    }
    background, text_color, border = mapping.get(priority, ("#f8fafc", "#334155", "#cbd5e1"))
    return (
        f"<span style='display:inline-block;padding:2px 8px;border:1px solid {border};"
        f"background:{background};color:{text_color};font-size:11px;font-weight:700;"
        f"letter-spacing:0.04em;'>{escape(priority)}</span>"
    )


def guardrail_badge(value: str) -> str:
    mapping = {
        "APPROVED": ("#f0fdf4", "#166534", "#bbf7d0"),
        "ESCALATED": ("#fef2f2", "#b91c1c", "#fecaca"),
        "BLOCKED": ("#fff7ed", "#9a3412", "#fed7aa"),
    }
    background, text_color, border = mapping.get(value, ("#f8fafc", "#475569", "#cbd5e1"))
    return (
        f"<span style='display:inline-block;padding:2px 8px;border:1px solid {border};"
        f"background:{background};color:{text_color};font-size:11px;font-weight:600;'>"
        f"{escape(format_action(value).upper())}</span>"
    )


def derived_status(case: dict[str, Any]) -> str:
    if case["recommended_action"] == "NO_ACTION":
        return "NO ACTION"
    if case["guardrail_status"] == "BLOCKED":
        return "BLOCKED"
    return "READY"


def status_badge(value: str) -> str:
    mapping = {
        "READY": ("#f0fdf4", "#166534", "#bbf7d0"),
        "NO ACTION": ("#f8fafc", "#475569", "#cbd5e1"),
        "BLOCKED": ("#fff7ed", "#9a3412", "#fed7aa"),
    }
    background, text_color, border = mapping.get(value, ("#f8fafc", "#475569", "#cbd5e1"))
    return (
        f"<span style='display:inline-block;padding:2px 8px;border:1px solid {border};"
        f"background:{background};color:{text_color};font-size:11px;font-weight:600;'>"
        f"{escape(value)}</span>"
    )


def optional_backend_value(value: Any, suffix: str = "") -> str:
    if value in (None, ""):
        return "Not available"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def percent_backend_value(value: Any) -> str:
    if value in (None, ""):
        return "Not available"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def guardrail_explanation(case: dict[str, Any]) -> str:
    status = case["guardrail_status"]
    action = case["recommended_action"]
    if status == "BLOCKED":
        return "This action is blocked by the guardrail, so execution is not available."
    if action == "NO_ACTION":
        return "No recovery action is available for this case."
    return "This action passed the guardrail check and is available for execution."


def is_executable(case: dict[str, Any]) -> bool:
    return case["recommended_action"] != "NO_ACTION" and case["guardrail_status"] != "BLOCKED"


def revenue_display(case: dict[str, Any]) -> str:
    amount = float(case["revenue_at_risk"])
    text = format_inr(amount)
    if case["case_type"] == "CHECKOUT_ABANDONMENT" and amount == 0:
        return f"{text}<br><span style='font-size:11px;color:#64748b;'>No monetary value available in source data.</span>"
    return text


def case_search_blob(case: dict[str, Any]) -> str:
    candidate_fields = ["case_id", "customer", "customer_name", "customer_id"]
    values = [str(case.get(field, "")) for field in candidate_fields]
    return " ".join(values).lower()


def apply_filters(
    cases: list[dict[str, Any]],
    filter_name: str,
    search_term: str,
    sort_by: str,
) -> list[dict[str, Any]]:
    filtered = list(cases)
    if filter_name == "High priority":
        filtered = [case for case in filtered if case["priority"] == "HIGH"]
    elif filter_name == "Checkout":
        filtered = [case for case in filtered if case["case_type"] == "CHECKOUT_ABANDONMENT"]
    elif filter_name == "Receivables":
        filtered = [case for case in filtered if case["case_type"] == "OVERDUE_RECEIVABLE"]
    elif filter_name == "Actionable":
        filtered = [case for case in filtered if case["recommended_action"] != "NO_ACTION"]
    elif filter_name == "No action":
        filtered = [case for case in filtered if case["recommended_action"] == "NO_ACTION"]

    term = search_term.strip().lower()
    if term:
        filtered = [case for case in filtered if term in case_search_blob(case)]

    if sort_by == "Priority":
        filtered.sort(key=lambda case: (PRIORITY_ORDER.get(case["priority"], 9), -float(case["risk_score"])))
    elif sort_by == "Revenue at Risk":
        filtered.sort(key=lambda case: float(case["revenue_at_risk"]), reverse=True)
    else:
        filtered.sort(key=lambda case: float(case["risk_score"]), reverse=True)
    return filtered


def queue_metrics(cases: list[dict[str, Any]], payload: dict[str, Any] | None) -> dict[str, int | float]:
    return {
        "revenue_at_risk": sum(float(case["revenue_at_risk"]) for case in cases),
        "cases_detected": int(payload["cases_detected"]) if payload else len(cases),
        "high_priority": sum(case["priority"] == "HIGH" for case in cases),
        "actions_recommended": int(payload["actions_recommended"]) if payload else sum(case["recommended_action"] != "NO_ACTION" for case in cases),
    }


def render_metric_card(label: str, value: str, detail: str = "") -> None:
    st.markdown(
        (
            "<div style='border:1px solid #e2e8f0;background:#ffffff;padding:14px 16px;"
            "box-shadow:0 1px 2px rgba(15,23,42,0.04);height:100%;'>"
            f"<div style='font-size:11px;font-weight:700;letter-spacing:0.08em;color:#64748b;'>{escape(label)}</div>"
            f"<div style='margin-top:10px;font-size:20px;font-weight:700;color:#0f172a;white-space:nowrap;'>{escape(value)}</div>"
            f"<div style='margin-top:6px;font-size:12px;color:#64748b;'>{escape(detail)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_source_card(title: str, count: int, subtitle: str, inactive: bool = False) -> None:
    accent = "#b91c1c" if not inactive else "#64748b"
    detail = f"{count} case" if count == 1 else f"{count} cases"
    st.markdown(
        (
            "<div style='border:1px solid #e2e8f0;background:#ffffff;padding:14px 16px;"
            "box-shadow:0 1px 2px rgba(15,23,42,0.04);height:100%;'>"
            f"<div style='font-size:11px;font-weight:700;letter-spacing:0.08em;color:#64748b;'>{escape(title)}</div>"
            f"<div style='margin-top:10px;font-size:20px;font-weight:700;color:#0f172a;'>{escape(detail)}</div>"
            f"<div style='margin-top:6px;font-size:12px;color:{accent};'>{escape(subtitle)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_queue_table(cases: list[dict[str, Any]]) -> None:
    header = st.columns([1.1, 2.3, 1.8, 1.6, 1.1, 2.0, 1.3, 1.2, 1.0])
    labels = [
        "Priority",
        "Case",
        "Type",
        "Revenue at Risk",
        "Risk Score",
        "Recommended Action",
        "Guardrail",
        "Status",
        "",
    ]
    for column, label in zip(header, labels):
        column.markdown(
            f"<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;color:#64748b;padding:4px 0 8px 0;'>{escape(label.upper())}</div>",
            unsafe_allow_html=True,
        )

    for case in cases:
        row = st.columns([1.1, 2.3, 1.8, 1.6, 1.1, 2.0, 1.3, 1.2, 1.0])
        row[0].markdown(priority_badge(case["priority"]), unsafe_allow_html=True)
        row[1].markdown(
            (
                f"<div style='font-family:monospace;font-size:12px;font-weight:600;color:#0f172a;'>{escape(case['case_id'])}</div>"
            ),
            unsafe_allow_html=True,
        )
        row[2].markdown(
            f"<div style='font-size:13px;color:#334155;'>{escape(format_type(case['case_type']))}</div>",
            unsafe_allow_html=True,
        )
        row[3].markdown(
            f"<div style='font-size:13px;font-weight:600;color:#0f172a;'>{revenue_display(case)}</div>",
            unsafe_allow_html=True,
        )
        row[4].markdown(
            f"<div style='font-size:13px;color:#0f172a;'>{float(case['risk_score']):.2f}</div>",
            unsafe_allow_html=True,
        )
        row[5].markdown(
            f"<div style='font-size:12px;font-weight:600;color:#0f172a;'>{escape(format_action(case['recommended_action']).upper())}</div>",
            unsafe_allow_html=True,
        )
        row[6].markdown(guardrail_badge(case["guardrail_status"]), unsafe_allow_html=True)
        row[7].markdown(status_badge(derived_status(case)), unsafe_allow_html=True)
        if row[8].button("Review", key=f"review_{case['case_id']}", use_container_width=True):
            st.session_state.selected_case_id = case["case_id"]
            st.session_state.drawer_view = "decision"
            st.session_state.latest_execution = None
            st.session_state.latest_execution_error = None
            start_case_details_load()
        st.markdown("<div style='border-bottom:1px solid #e2e8f0;margin:8px 0 6px 0;'></div>", unsafe_allow_html=True)


def render_o2c_drawer(case: dict[str, Any]) -> None:
    revenue_reasoning = case.get("revenue_reasoning", {})
    late_payment_probability = case.get("late_payment_probability") or revenue_reasoning.get("late_payment_probability")
    days_overdue = case.get("days_overdue")
    customer = case.get("customer") or case.get("customer_name") or case.get("customer_id") or "Not available"

    with st.container(border=True):
        header_cols = st.columns([0.62, 0.38])
        with header_cols[0]:
            st.markdown("**OVERDUE RECEIVABLE**")
            st.markdown(f"`{case['case_id']}`")
            st.caption(f"Customer: {customer}")
        with header_cols[1]:
            st.markdown(priority_badge(case["priority"]), unsafe_allow_html=True)
            st.markdown(f"**{format_inr(float(case['revenue_at_risk']))}**")
            st.caption(f"Days overdue: {optional_backend_value(days_overdue)}")

        st.divider()
        st.markdown("**01 - Risk Assessment**")
        risk_cols = st.columns(3)
        assessment_metrics = (
            ("Late-payment probability", percent_backend_value(late_payment_probability)),
            ("Risk score", f"{float(case['risk_score']):.2f}"),
            ("Priority", case["priority"]),
        )
        for column, (label, value) in zip(risk_cols, assessment_metrics):
            column.markdown(
                (
                    f"<div style='font-size:12px;font-weight:600;color:#64748b;'>{escape(label)}</div>"
                    f"<div style='margin-top:6px;font-size:20px;font-weight:700;color:#0f172a;'>{escape(value)}</div>"
                ),
                unsafe_allow_html=True,
            )

        st.markdown("**02 - Why This Case**")
        st.write(case["reason"])

        st.markdown("**03 - Agent Decision**")
        st.markdown(f"Recommended action: **{format_action(case['recommended_action']).upper()}**")
        if "confidence" in case and case["confidence"] is not None:
            st.markdown(f"Confidence: **{float(case['confidence']) * 100:.0f}%**")
        st.caption("Decision reason")
        st.write(case["reason"])

        st.markdown("**04 - Guardrail**")
        st.markdown(guardrail_badge(case["guardrail_status"]), unsafe_allow_html=True)
        st.caption(guardrail_explanation(case))

        st.divider()
        if is_executable(case):
            if st.button("Execute recovery action", type="primary", use_container_width=True):
                execution_error = execute_case(case["case_id"])
                if execution_error:
                    st.error(execution_error)
                else:
                    st.rerun()
        else:
            st.info("No executable recovery action is available for this case.")

        if st.session_state.latest_execution and st.session_state.latest_execution["decision"]["case_id"] == case["case_id"]:
            execution = st.session_state.latest_execution["execution"]
            st.caption(
                "Execution status: "
                f"{execution.get('status', 'status unavailable')} for "
                f"{execution.get('action', case['recommended_action'])}"
            )
        if st.session_state.latest_execution_error:
            st.error(st.session_state.latest_execution_error)

        if st.button("Back to work queue", use_container_width=True):
            close_drawer()
            st.rerun()


def render_checkout_drawer(case: dict[str, Any]) -> None:
    with st.container(border=True):
        header_cols = st.columns([0.62, 0.38])
        with header_cols[0]:
            st.markdown("**CHECKOUT ABANDONMENT**")
            st.markdown(f"`{case['case_id']}`")
        with header_cols[1]:
            st.markdown(priority_badge(case["priority"]), unsafe_allow_html=True)
            st.markdown(f"Revenue at risk: **{format_inr(float(case['revenue_at_risk']))}**")

        if float(case["revenue_at_risk"]) == 0:
            st.caption("**No monetary value available in source data.**")

        st.divider()
        st.markdown("**01 - Risk & Propensity Assessment**")
        risk_cols = st.columns(3)
        assessment_metrics = (
            ("Recovery probability", optional_backend_value(case.get("recovery_probability"))),
            ("Risk score", optional_backend_value(case.get("risk_score"))),
            ("Priority", optional_backend_value(case.get("priority"))),
        )
        for column, (label, value) in zip(risk_cols, assessment_metrics):
            column.markdown(
                (
                    f"<div style='font-size:12px;font-weight:600;color:#64748b;'>{escape(label)}</div>"
                    f"<div style='margin-top:6px;font-size:20px;font-weight:700;color:#0f172a;'>{escape(value)}</div>"
                ),
                unsafe_allow_html=True,
            )

        st.markdown("**02 - Why This Case**")
        st.write(case["reason"])

        st.markdown("**03 - Agent Decision**")
        st.markdown(f"Recommended action: **{format_action(case['recommended_action']).upper()}**")
        if "confidence" in case and case["confidence"] is not None:
            st.markdown(f"Confidence: **{float(case['confidence']) * 100:.0f}%**")
        st.caption("Decision reason")
        st.write(case["reason"])

        st.markdown("**04 - Guardrail**")
        st.markdown(guardrail_badge(case["guardrail_status"]), unsafe_allow_html=True)
        st.caption(guardrail_explanation(case))

        st.divider()
        st.markdown("**NO ACTION REQUIRED**")
        st.caption("The decision engine determined that an intervention is not currently justified.")

        if st.button("Return to work queue", use_container_width=True):
            close_drawer()
            st.rerun()


def render_execution_result_drawer(case: dict[str, Any], execution_payload: dict[str, Any]) -> None:
    decision = execution_payload.get("decision", {})
    execution = execution_payload.get("execution", {})
    action = str(execution.get("action") or decision.get("recommended_action") or case["recommended_action"])
    status = str(execution.get("status", "Status not provided"))
    simulated = execution.get("simulated")
    simulated_label = "YES" if simulated is True else "NO" if simulated is False else "Not available"

    with st.container(border=True):
        header_cols = st.columns([0.62, 0.38])
        with header_cols[0]:
            st.markdown("**Recovery action executed**")
            st.markdown(f"`{case['case_id']}`")
        with header_cols[1]:
            st.markdown(guardrail_badge(action), unsafe_allow_html=True)
            st.markdown(f"Status: **{escape(status)}**")

        st.divider()
        st.markdown("**01 - Execution**")
        exec_cols = st.columns([1.15, 1.15, 1.15])
        execution_fields = (
            ("Action", action),
            ("Status", status),
            ("Simulated", simulated_label),
        )
        for column, (label, value) in zip(exec_cols, execution_fields):
            with column:
                st.markdown(
                    (
                        f"<div style='font-size:11px;font-weight:600;color:#64748b;"
                        f"text-transform:uppercase;letter-spacing:0.06em;'>{escape(label)}</div>"
                        f"<div style='margin-top:6px;font-size:15px;font-weight:700;"
                        f"color:#0f172a;white-space:nowrap;'>{escape(str(value))}</div>"
                    ),
                    unsafe_allow_html=True,
                )
        execution_id = execution.get("execution_id")
        if execution_id:
            st.caption(f"Execution ID: {execution_id}")

        st.markdown("**02 - Execution Message**")
        if execution.get("message") is not None:
            st.write(execution["message"])

        st.markdown("**03 - Recovery Context**")
        context_rows = [
            ("Case ID", case["case_id"]),
            ("Case type", format_type(case["case_type"])),
            ("Revenue at risk", format_inr(float(case["revenue_at_risk"]))),
            ("Recommended action", format_action(case["recommended_action"]).upper()),
            ("Executed action", action),
        ]
        for label, value in context_rows:
            st.markdown(f"**{label}:** {escape(str(value))}")

        st.divider()
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("Return to work queue", use_container_width=True):
                close_drawer()
                st.rerun()
        with action_cols[1]:
            if st.button("View case decision", use_container_width=True):
                st.session_state.drawer_view = "decision"
                st.rerun()


@st.fragment(run_every=0.2)
def render_case_drawer_content() -> None:
    if st.session_state.case_details_loading:
        future: Future[tuple[dict[str, Any] | None, str | None]] | None = st.session_state.case_details_future
        if future is None:
            start_case_details_load()
        elif future.done():
            try:
                payload, api_error = future.result()
            except Exception:
                payload, api_error = None, "The frontend could not load this case."
            st.session_state.case_details_future = None
            if api_error:
                st.session_state.case_details_loading = False
                st.session_state.case_details_error = api_error
            else:
                st.session_state.latest_payload = payload
                st.session_state.latest_cases = (payload or {}).get("cases", [])
                st.session_state.case_details_loading = False
                st.session_state.case_details_error = None
            st.rerun()

        st.info("Loading case details…")
        return

    selected_case = find_selected_case()
    if selected_case is None:
        st.error(st.session_state.case_details_error or "This case could not be loaded.")
        retry_cols = st.columns(2)
        with retry_cols[0]:
            if st.button("Retry loading details", use_container_width=True):
                start_case_details_load()
                st.rerun()
        with retry_cols[1]:
            if st.button("Return to work queue", use_container_width=True):
                close_drawer()
                st.rerun()
        return

    execution_payload = st.session_state.latest_execution
    execution_matches_case = isinstance(execution_payload, dict)
    if execution_matches_case:
        execution_matches_case = execution_payload.get("decision", {}).get("case_id") == selected_case["case_id"]
    if st.session_state.drawer_view == "execution" and execution_matches_case:
        render_execution_result_drawer(selected_case, execution_payload)
    elif selected_case["case_type"] == "CHECKOUT_ABANDONMENT":
        render_checkout_drawer(selected_case)
    else:
        render_o2c_drawer(selected_case)


def main() -> None:
    st.set_page_config(page_title="Revenue Recovery", layout="wide")
    init_state()

    st.markdown(
        """
        <style>
        .stApp {
            background: #f8fafc;
            color: #0f172a;
        }
        .block-container {
            max-width: 1340px;
            padding-top: 1rem;
            padding-bottom: 2rem;
        }
        div[data-testid="stHorizontalBlock"] > div {
            align-self: stretch;
        }
        div[data-baseweb="input"] input {
            background: #ffffff;
            color: #0f172a;
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] {
            background: #ffffff;
            border-color: #cbd5e1;
            color: #0f172a;
        }
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
            background-color: #ffffff !important;
            border: 1px solid #cbd5e1 !important;
            color: #334155 !important;
            -webkit-text-fill-color: #334155 !important;
            box-shadow: none !important;
        }
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:hover,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:focus,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:focus-visible {
            background-color: #f8fafc !important;
            border-color: #94a3b8 !important;
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            box-shadow: 0 0 0 2px rgba(185, 28, 28, 0.12) !important;
        }
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"],
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected="true"],
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"]:hover,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected="true"]:hover,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"]:focus,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected="true"]:focus,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"]:focus-visible,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected="true"]:focus-visible {
            background-color: #fff1f2 !important;
            border-color: #b91c1c !important;
            color: #991b1b !important;
            -webkit-text-fill-color: #991b1b !important;
            font-weight: 700;
            box-shadow: 0 0 0 2px rgba(185, 28, 28, 0.16) !important;
        }
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"] > *,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"] p,
        div[data-testid="stButtonGroup"] button[data-variant="segmented_control"] span {
            color: inherit !important;
            -webkit-text-fill-color: inherit !important;
        }
        .stButton button {
            border-radius: 4px;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            color: #0f172a;
            font-weight: 600;
        }
        div[data-testid="stBaseButton-primary"] > button {
            background: #b91c1c;
            color: #ffffff;
            border-color: #b91c1c;
        }
        .drawer-backdrop {
            position: fixed;
            inset: 0;
            z-index: 999;
            background: rgba(15, 23, 42, 0.12);
            backdrop-filter: blur(2px);
            -webkit-backdrop-filter: blur(2px);
            pointer-events: auto;
        }
        .st-key-drawer-backdrop-close {
            position: fixed;
            inset: 0;
            z-index: 999;
            pointer-events: auto;
        }
        .st-key-drawer-backdrop-close button {
            width: 100%;
            height: 100%;
            padding: 0;
            border: 0;
            background: transparent;
            color: transparent;
            opacity: 0;
            cursor: default;
        }
        .st-key-case-drawer {
            position: fixed;
            top: 0.75rem;
            right: 0.75rem;
            bottom: 0.75rem;
            z-index: 1000;
            width: min(430px, calc(100vw - 1.5rem));
            overflow-y: auto;
            padding: 0.75rem;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16);
        }
        @media (max-width: 640px) {
            .st-key-case-drawer {
                top: 0.5rem;
                right: 0.5rem;
                bottom: 0.5rem;
                width: calc(100vw - 1rem);
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.latest_payload is None:
        refresh_cases()

    left, right = st.columns([0.72, 0.28])
    with left:
        title_cols = st.columns([0.84, 0.16])
        with title_cols[0]:
            st.title("Revenue Recovery")
            st.caption("Recovery operations for identifying and acting on revenue at risk")
        with title_cols[1]:
            with st.popover("ⓘ Info", use_container_width=True):
                st.markdown(
                    "**Revenue at Risk** is the value associated with detected recovery cases; it is not a guaranteed loss or recovery.\n\n"
                    "**Recovery Probability / Propensity** is the model-estimated likelihood associated with a case, not causal intervention uplift.\n\n"
                    "**Risk Score** supports case prioritization. **Priority** is the operational priority assigned by the decision system.\n\n"
                    "**Recommended Action** is the intervention selected by the decision engine. **Guardrail** is the authorization check applied before execution."
                )
    with right:
        st.caption(format_last_scanned())
        if st.button("Scan for revenue at risk", type="primary", use_container_width=True):
            scan_error = run_scan()
            if scan_error:
                st.error(scan_error)
            else:
                st.success("Recovery queue refreshed from the backend.")

    payload = st.session_state.latest_payload
    cases = st.session_state.latest_cases
    latest_error = st.session_state.latest_error

    if payload is None:
        if latest_error:
            if "No revenue scan has run" in latest_error:
                st.info(latest_error)
            else:
                st.error(latest_error)
        else:
            st.error("The frontend could not load a recovery queue.")
        return

    if not cases:
        st.info("No revenue scan has run yet, or the latest work queue is empty.")
        return

    drawer_open = bool(st.session_state.selected_case_id)
    content_area = [st.container()]

    with content_area[0]:
        metrics = queue_metrics(cases, payload)
        metric_cols = st.columns(4)
        with metric_cols[0]:
            render_metric_card("REVENUE AT RISK", format_inr(float(metrics["revenue_at_risk"])), "Value associated with the current queue.")
        with metric_cols[1]:
            render_metric_card("CASES DETECTED", str(metrics["cases_detected"]), "Cases in the current recovery queue.")
        with metric_cols[2]:
            render_metric_card("HIGH PRIORITY", str(metrics["high_priority"]), "Current queue items marked HIGH.")
        with metric_cols[3]:
            render_metric_card("ACTIONS RECOMMENDED", str(metrics["actions_recommended"]), "Cases with a recommended action other than NO_ACTION.")

        st.markdown("### Revenue-risk sources")
        st.caption("Where the current recovery queue is coming from.")
        counts = source_counts(cases)
        source_cols = st.columns(3)
        with source_cols[0]:
            render_source_card("OVERDUE RECEIVABLES", counts["OVERDUE_RECEIVABLE"], "Current source active.")
        with source_cols[1]:
            render_source_card("CHECKOUT ABANDONMENTS", counts["CHECKOUT_ABANDONMENT"], "Current source active.")
        with source_cols[2]:
            subtitle = "No source data configured" if counts["PAYMENT_FAILURE"] == 0 else "Current source active."
            render_source_card("PAYMENT FAILURES", counts["PAYMENT_FAILURE"], subtitle, inactive=counts["PAYMENT_FAILURE"] == 0)

        st.markdown("### Recovery work queue")
        st.caption("Prioritized cases requiring review or recovery action.")

        control_cols = st.columns([2.8, 1.5, 1.1])
        with control_cols[0]:
            filter_name = st.segmented_control(
                "Queue filter",
                ["All", "High priority", "Checkout", "Receivables", "Actionable", "No action"],
                default="All",
                label_visibility="collapsed",
            )
        with control_cols[1]:
            sort_by = st.selectbox("Sort", ["Priority", "Revenue at Risk", "Risk Score"], index=0)
        with control_cols[2]:
            st.session_state.queue_page_size = st.selectbox(
                "Rows",
                PAGE_SIZE_OPTIONS,
                index=PAGE_SIZE_OPTIONS.index(st.session_state.queue_page_size) if st.session_state.queue_page_size in PAGE_SIZE_OPTIONS else 0,
            )

        search_term = st.text_input("Search by Case ID or Customer", placeholder="Search by Case ID or Customer")
        filtered_cases = apply_filters(cases, filter_name, search_term, sort_by)

        if not filtered_cases:
            st.info("No cases match the current search and filter settings.")
        else:
            page_size = int(st.session_state.queue_page_size)
            total_cases = len(filtered_cases)
            total_pages = max(1, math.ceil(total_cases / page_size))
            st.session_state.queue_page = min(max(1, st.session_state.queue_page), total_pages)
            start_index = (st.session_state.queue_page - 1) * page_size
            end_index = min(start_index + page_size, total_cases)
            page_cases = filtered_cases[start_index:end_index]

            with st.container(border=True):
                render_queue_table(page_cases)

            footer_cols = st.columns([0.55, 0.45])
            with footer_cols[0]:
                st.caption(f"Showing {start_index + 1}-{end_index} of {total_cases} cases")
            with footer_cols[1]:
                nav_cols = st.columns([1, 1, 1])
                with nav_cols[0]:
                    if st.button("Previous", disabled=st.session_state.queue_page == 1, use_container_width=True):
                        st.session_state.queue_page -= 1
                        st.rerun()
                with nav_cols[1]:
                    st.markdown(
                        f"<div style='text-align:center;padding-top:8px;font-size:12px;color:#475569;'>Page {st.session_state.queue_page} of {total_pages}</div>",
                        unsafe_allow_html=True,
                    )
                with nav_cols[2]:
                    if st.button("Next", disabled=st.session_state.queue_page == total_pages, use_container_width=True):
                        st.session_state.queue_page += 1
                        st.rerun()

    if drawer_open:
        st.html(
            """
            <script>
            (() => {
                if (window.__revenueRecoveryDrawerHandlersBound) return;
                window.__revenueRecoveryDrawerHandlersBound = true;
                const closeDrawer = () => Array.from(document.querySelectorAll("button")).find(
                    (button) => ["Back to work queue", "Return to work queue"].includes(button.innerText.trim())
                )?.click();
                document.addEventListener("keydown", (event) => {
                    if (event.key === "Escape") closeDrawer();
                });
                document.addEventListener("click", (event) => {
                    if (event.target.closest(".drawer-backdrop")) closeDrawer();
                });
            })();
            </script>
            """,
            unsafe_allow_javascript=True,
        )
        render_drawer_backdrop()
        with st.container(key="case-drawer"):
            render_case_drawer_content()
    st.markdown(
        (
            "<div style='margin-top:18px;border:1px solid #e2e8f0;background:#fff7f7;padding:14px 16px;'>"
            "<div style='font-size:12px;font-weight:700;letter-spacing:0.08em;color:#991b1b;'>RECOVERY GUARDRAILS ACTIVE</div>"
            "<div style='margin-top:6px;font-size:13px;color:#334155;'>"
            "Recommended recovery actions are validated against configured recovery policies before execution."
            "</div></div>"
        ),
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
