"""
Score open O2C invoices using the validated late-payment model.

Run from the repository root:
    python scripts/evaluation/score_o2c_open_invoices.py

This produces model scores only. It does not make intervention decisions.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.models.o2c import MODEL_FEATURES, score_o2c_cases

REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "receivables"
    / "o2c_features.csv"
)

OUTPUT_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "receivables"
    / "o2c_scored_open_invoices.csv"
)


def main() -> None:
    df = pd.read_csv(INPUT_PATH)

    open_invoices = df[df["record_type"] == "open"].copy()

    probabilities = score_o2c_cases(open_invoices[MODEL_FEATURES])

    if probabilities is None:
        raise RuntimeError("O2C batch prediction failed.")

    open_invoices["late_payment_probability"] = probabilities

    open_invoices["risk_tier"] = pd.cut(
        open_invoices["late_payment_probability"],
        bins=[-float("inf"), 0.50, 0.75, float("inf")],
        labels=["LOW", "MEDIUM", "HIGH"],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    open_invoices.to_csv(OUTPUT_PATH, index=False)

    print(f"Open invoices scored: {len(open_invoices):,}")
    print(
        "Missing probabilities:",
        int(open_invoices["late_payment_probability"].isna().sum()),
    )

    print("\nRisk tiers:")
    print(open_invoices["risk_tier"].value_counts().sort_index())

    print("\nProbability summary:")
    print(open_invoices["late_payment_probability"].describe())

    print(f"\nOutput: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
