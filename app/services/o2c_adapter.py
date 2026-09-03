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

    return RecoveryCase(
        case_id=f"o2c_{int(row['invoice_id'])}",
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id=str(row["cust_number"]),
        revenue_at_risk=float(row["total_open_amount"]),
        context={
            "payment_status": "open",
            "days_overdue": 0,
            "is_priority_account": False,
            "customer_tier": "standard",
            "days_since_last_reminder": None,
            "late_payment_probability": float(
                row["late_payment_probability"]
            ),
        },
    )
