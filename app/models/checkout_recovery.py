"""
Checkout-recovery Random Forest wrapper.

Loads selected_recovery_model.pkl from ml/checkout/artifacts/ via the
centralized path in app.config.settings.

The model expects exactly 7 features (in this order):
  cart_additions, views, unique_products, event_count,
  duration_minutes, hour_of_day, day_of_week

score_checkout_case() returns None when any required feature is absent,
allowing callers to fall back to a manually supplied propensity score.

IMPORTANT: the score is a propensity / prioritization signal.
           It is NOT a causal estimate of intervention-lift.
"""

from __future__ import annotations

import joblib
import warnings
from typing import Any

import numpy as np

from app.config.settings import CHECKOUT_MODEL_PATH

# Feature contract — must match training order.
MODEL_FEATURES: list[str] = [
    "cart_additions",
    "views",
    "unique_products",
    "event_count",
    "duration_minutes",
    "hour_of_day",
    "day_of_week",
]

_model = None   # lazy-loaded singleton


def _load_model():
    global _model
    if _model is not None:
        return _model
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # suppress sklearn version-mismatch warning
        with open(CHECKOUT_MODEL_PATH, "rb") as f:
            _model = joblib.load(f)
    return _model


def score_checkout_case(context: dict[str, Any]) -> float | None:
    """
    Return P(recovered_within_7d) for the given session context, or None
    if any required feature is missing.

    Parameters
    ----------
    context : dict
        Must contain all MODEL_FEATURES keys with numeric values.

    Returns
    -------
    float in [0, 1] or None
    """
    if not all(k in context for k in MODEL_FEATURES):
        return None

    try:
        model = _load_model()
        row   = np.array([[context[k] for k in MODEL_FEATURES]], dtype=float)
        return float(model.predict_proba(row)[0, 1])
    except Exception:
        return None
