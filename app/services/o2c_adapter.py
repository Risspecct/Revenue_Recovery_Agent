"""
Adapter for converting scored O2C invoices into RecoveryCase objects.

This module bridges the O2C ML scoring layer and the Recovery Decision Engine.

ML predicts late-payment risk.
The Decision Engine remains responsible for intervention selection.
"""

from __future__ import annotations

from typing import Any

from app.decision.schemas import CaseType, RecoveryCase


def build_o2c_case(row: dict[str, Any]) -> RecoveryCase:
    """
    Convert one scored O2C invoice into a RecoveryCase.
    """

    invoice_id = str(row["invoice_id"])
    if invoice_id.endswith(".0"):
        invoice_id = invoice_id[:-2]
    reminder_age = row.get("days_since_last_reminder")
    if reminder_age not in (None, ""):
        reminder_age = int(float(reminder_age))

    return RecoveryCase(
        case_id=f"o2c_{invoice_id}",
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id=str(row["cust_number"]),
        revenue_at_risk=float(row["total_open_amount"]),
        context={
            "payment_status": str(row.get("payment_status", "open")),
            "days_overdue": int(row.get("days_overdue", 0)),
            "is_priority_account": str(row.get("is_priority_account", "false")).lower() in {"1", "true", "yes"},
            "customer_tier": str(row.get("customer_tier", "standard")),
            "days_since_last_reminder": reminder_age,
            "late_payment_probability": float(
                row["late_payment_probability"]
            ),
        },
    )
