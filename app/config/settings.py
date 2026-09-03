"""
Application settings.

All path constants and environment-driven config live here.
Use repository-relative paths so the project runs from any working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root — everything is relative to this
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parents[2]  # app/config/ → repo root

# ---------------------------------------------------------------------------
# ML artifact paths
# ---------------------------------------------------------------------------

ML_ARTIFACTS_DIR: Path = REPO_ROOT / "ml" / "checkout" / "artifacts"

CHECKOUT_MODEL_PATH: Path = ML_ARTIFACTS_DIR / "selected_recovery_model.pkl"
O2C_MODEL_PATH: Path = (REPO_ROOT / "ml" / "o2c" / "artifacts" / "selected_o2c_late_payment_model.pkl")
BASELINE_MODEL_PATH: Path = ML_ARTIFACTS_DIR / "baseline_recovery_model.pkl"
FEATURE_SCALER_PATH: Path = ML_ARTIFACTS_DIR / "feature_scaler.pkl"

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------

DATA_DIR: Path = REPO_ROOT / "data"

RAW_CHECKOUT_DIR:       Path = DATA_DIR / "raw"  / "checkout"
RAW_PAYMENT_DIR:        Path = DATA_DIR / "raw"  / "payment"
RAW_RECEIVABLES_DIR:    Path = DATA_DIR / "raw"  / "receivables"

PROCESSED_CHECKOUT_DIR:    Path = DATA_DIR / "processed" / "checkout"
PROCESSED_PAYMENT_DIR:     Path = DATA_DIR / "processed" / "payment"
PROCESSED_RECEIVABLES_DIR: Path = DATA_DIR / "processed" / "receivables"

# Event log used for checkout EDA and model training
EVENTS_CSV: Path = RAW_CHECKOUT_DIR / "events.csv"

# ---------------------------------------------------------------------------
# Application settings (override via environment variables)
# ---------------------------------------------------------------------------

APP_TITLE:   str = os.getenv("APP_TITLE",   "RazorPay Track 03 — Recovery Engine")
APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")
DEBUG:       bool = os.getenv("DEBUG", "false").lower() == "true"
