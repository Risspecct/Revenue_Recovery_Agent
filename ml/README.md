# ML Directory

## Structure

```
ml/
└── checkout/
    ├── artifacts/
    │   ├── selected_recovery_model.pkl   ← Trained Random Forest (primary)
    │   ├── baseline_recovery_model.pkl   ← Baseline model (future)
    │   └── feature_scaler.pkl            ← Feature scaler (future)
    ├── train/                            ← Training scripts (future)
    └── evaluation/                       ← Evaluation scripts (future)
```

## Checkout Recovery Model

- Type: Random Forest Classifier
- Target: `recovered_within_7d`
- Features: `cart_additions`, `views`, `unique_products`, `event_count`,
  `duration_minutes`, `hour_of_day`, `day_of_week`
- Test ROC-AUC: 0.5954
- Test PR-AUC: 0.0871
- Top-10% recovery rate: 8.70% (1.61× baseline lift)
- Trained with scikit-learn 1.6.1

**Important:** The model score is a propensity/prioritization signal.
It is NOT a causal intervention-lift estimate.

## Loading

```python
from app.models.checkout_recovery import score_checkout_case

prob = score_checkout_case({
    "cart_additions": 3, "views": 12, "unique_products": 4,
    "event_count": 25, "duration_minutes": 8.5,
    "hour_of_day": 14, "day_of_week": 2,
})
```

Model path is configured in `app/config/settings.py → CHECKOUT_MODEL_PATH`.
