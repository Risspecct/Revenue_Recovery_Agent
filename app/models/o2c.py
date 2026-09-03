"""
O2C late-payment risk Random Forest wrapper.

Loads selected_o2c_late_payment_model.pkl from ml/o2c/artifacts/
via the centralized path in app.config.settings.

The model expects exactly 14 features in the training order.

IMPORTANT:
    This model predicts late-payment risk.
    It does NOT predict recovery probability or intervention uplift.
"""

from __future__ import annotations

import joblib
import warnings
from typing import Any
import numpy as np
import pandas as pd

from app.config.settings import O2C_MODEL_PATH


# Feature contract — must match O2C model training order.
MODEL_FEATURES: list[str] = [
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

_model = None


def _load_model():
    global _model

    if _model is not None:
        return _model

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        with open(O2C_MODEL_PATH, "rb") as f:
            _model = joblib.load(f)

    return _model


def score_o2c_case(context: dict[str, Any]) -> float | None:
    """
    Return P(late_payment) for the given invoice context.

    Returns None if any required model feature is missing or inference fails.
    """

    if not all(k in context for k in MODEL_FEATURES):
        return None

    try:
        model = _load_model()

        row = pd.DataFrame(
            [[context[k] for k in MODEL_FEATURES]],
            columns=MODEL_FEATURES,
        )

        return round(float(model.predict_proba(row)[0, 1]), 6)

    except Exception:
        return None


def score_o2c_cases(
    features: pd.DataFrame,
) -> np.ndarray | None:
    """
    Return P(late_payment) for multiple invoices in one batch.

    The DataFrame must contain all MODEL_FEATURES columns.
    Returns None if required features are missing or inference fails.
    """

    if not all(k in features.columns for k in MODEL_FEATURES):
        return None

    try:
        model = _load_model()

        row = features[MODEL_FEATURES].copy()

        probabilities = model.predict_proba(row)[:, 1]

        return np.round(probabilities.astype(float), 6)

    except Exception:
        return None
