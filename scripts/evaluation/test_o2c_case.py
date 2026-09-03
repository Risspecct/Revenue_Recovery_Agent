"""
Test one real scored O2C invoice through the Recovery Decision Engine.

This is an integration test using a real invoice from the processed dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.decision.engine import decide
from app.decision.schemas import CaseType, RecoveryCase


REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "receivables"
    / "o2c_scored_open_invoices.csv"
)


def main() -> None:
    df = pd.read_csv(INPUT_PATH)

    # Use the highest-risk real open invoice as the demonstration case.
    row = df.loc[df["late_payment_probability"].idxmax()]

    context = {
        "payment_status": "open",
        "days_overdue": 0,
        "is_priority_account": False,
        "customer_tier": "standard",
        "days_since_last_reminder": None,
        "late_payment_probability": float(row["late_payment_probability"]),
    }

    case = RecoveryCase(
        case_id=f"o2c_{int(row['invoice_id'])}",
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id=str(row["cust_number"]),
        revenue_at_risk=float(row["total_open_amount"]),
        context=context,
    )

    result = decide(case)

    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
