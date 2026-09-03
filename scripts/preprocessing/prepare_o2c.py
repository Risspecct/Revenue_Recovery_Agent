"""
Prepare O2C receivables data for the Revenue Recovery Agent.

Source:
    data/raw/receivables/dataset.csv

Output:
    data/processed/receivables/o2c_features.csv

The customer-history features are leakage-free:
history for an invoice only uses outcomes from strictly earlier due dates.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = REPO_ROOT / "data" / "raw" / "receivables" / "dataset.csv"
OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "receivables"
OUTPUT_PATH = OUTPUT_DIR / "o2c_features.csv"


FEATURE_COLS = [
    "invoice_amount",
    "posting_to_due_days",
    "due_month",
    "due_day_of_week",
    "posting_month",
    "business_code",
    "invoice_currency",
    "cust_payment_terms",
    "prior_invoice_count",
    "prior_late_rate",
    "prior_avg_days_late",
    "prior_median_days_late",
    "prior_avg_invoice_amount",
    "prior_max_days_late",
]


def load_and_clean() -> pd.DataFrame:
    df = pd.read_csv(INPUT_PATH)

    # Parse date columns.
    df["posting_date"] = pd.to_datetime(
        df["posting_date"],
        errors="coerce",
    )

    df["clear_date"] = pd.to_datetime(
        df["clear_date"],
        errors="coerce",
    )

    df["due_date"] = pd.to_datetime(
        df["due_in_date"].astype("Int64").astype(str),
        format="%Y%m%d",
        errors="coerce",
    )

    # Remove exact duplicate rows.
    df = df.drop_duplicates().copy()

    return df


def build_closed_history(closed: pd.DataFrame) -> pd.DataFrame:
    """
    Build customer history using only strictly earlier due-date groups.
    """

    closed = closed.copy()

    closed["days_late"] = (
        closed["clear_date"] - closed["due_date"]
    ).dt.days

    closed["late_payment"] = (
        closed["clear_date"] > closed["due_date"]
    ).astype(int)

    daily_customer = (
        closed
        .groupby(["cust_number", "due_date"], as_index=False)
        .agg(
            invoice_count=("late_payment", "size"),
            late_count=("late_payment", "sum"),
            avg_days_late=(
                "days_late",
                lambda x: x.clip(lower=0).mean(),
            ),
            median_days_late=(
                "days_late",
                lambda x: x.clip(lower=0).median(),
            ),
            avg_invoice_amount=("total_open_amount", "mean"),
            max_days_late=(
                "days_late",
                lambda x: x.clip(lower=0).max(),
            ),
        )
        .sort_values(["cust_number", "due_date"])
    )

    g = daily_customer.groupby("cust_number")

    # Exclude the current due-date group from every history feature.
    daily_customer["prior_invoice_count"] = (
        g["invoice_count"].cumsum()
        - daily_customer["invoice_count"]
    )

    daily_customer["prior_late_count"] = (
        g["late_count"].cumsum()
        - daily_customer["late_count"]
    )

    daily_customer["prior_late_rate"] = (
        daily_customer["prior_late_count"]
        / daily_customer["prior_invoice_count"].replace(0, np.nan)
    ).fillna(0)

    daily_customer["prior_avg_days_late"] = (
        g["avg_days_late"]
        .transform(lambda x: x.shift(1).expanding().mean())
    ).fillna(0)

    daily_customer["prior_median_days_late"] = (
        g["median_days_late"]
        .transform(lambda x: x.shift(1).expanding().median())
    ).fillna(0)

    daily_customer["prior_avg_invoice_amount"] = (
        g["avg_invoice_amount"]
        .transform(lambda x: x.shift(1).expanding().mean())
    ).fillna(0)

    daily_customer["prior_max_days_late"] = (
        g["max_days_late"]
        .transform(lambda x: x.shift(1).expanding().max())
    ).fillna(0)

    return daily_customer[
        [
            "cust_number",
            "due_date",
            "prior_invoice_count",
            "prior_late_rate",
            "prior_avg_days_late",
            "prior_median_days_late",
            "prior_avg_invoice_amount",
            "prior_max_days_late",
        ]
    ]


def add_history_features(
    invoices: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    """
    Attach the most recent strictly earlier customer history.

    merge_asof is used instead of an exact customer/date merge because
    open invoices may have due dates for which no closed invoice exists.
    """

    invoices = invoices.sort_values(
        ["due_date", "cust_number"]
    ).copy()

    history = history.sort_values(
        ["due_date", "cust_number"]
    ).copy()

    result = pd.merge_asof(
        invoices,
        history,
        on="due_date",
        by="cust_number",
        direction="backward",
        allow_exact_matches=False,
    )

    history_cols = [
        "prior_invoice_count",
        "prior_late_rate",
        "prior_avg_days_late",
        "prior_median_days_late",
        "prior_avg_invoice_amount",
        "prior_max_days_late",
    ]

    result[history_cols] = result[history_cols].fillna(0)

    return result


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the final 14-feature representation used by the O2C model.
    """

    result = df.copy()

    result["invoice_amount"] = result["total_open_amount"]

    result["posting_to_due_days"] = (
        result["due_date"] - result["posting_date"]
    ).dt.days

    result["due_month"] = result["due_date"].dt.month
    result["due_day_of_week"] = result["due_date"].dt.dayofweek
    result["posting_month"] = result["posting_date"].dt.month

    result = result[FEATURE_COLS + [
        "id",
        "cust_number",
        "due_date",
        "posting_date",
        "clear_date",
        "isOpen",
        "total_open_amount",
    ]]

    return result


def main() -> None:
    df = load_and_clean()

    closed = df[df["isOpen"] == 0].copy()
    open_invoices = df[df["isOpen"] == 1].copy()

    history = build_closed_history(closed)

    closed = add_history_features(closed, history)
    open_invoices = add_history_features(open_invoices, history)

    closed_features = build_features(closed)
    open_features = build_features(open_invoices)

    closed_features["late_payment"] = (
        closed_features["clear_date"]
        > closed_features["due_date"]
    ).astype(int)

    closed_features["days_late"] = (
        closed_features["clear_date"]
        - closed_features["due_date"]
    ).dt.days

    closed_features["record_type"] = "closed"
    open_features["record_type"] = "open"

    result = pd.concat(
        [closed_features, open_features],
        ignore_index=True,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)

    print(f"Input rows: {len(df):,}")
    print(f"Closed invoices: {len(closed_features):,}")
    print(f"Open invoices: {len(open_features):,}")
    print(f"Output rows: {len(result):,}")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
