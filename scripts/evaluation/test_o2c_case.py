"""
Test the O2C adapter with a real scored invoice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.decision.engine import decide
from app.services.o2c_adapter import build_o2c_case


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

    row = df.loc[df["late_payment_probability"].idxmax()]

    case = build_o2c_case(row.to_dict())

    result = decide(case)

    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
