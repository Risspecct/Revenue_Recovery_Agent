# Data Directory

## Structure

```
data/
├── raw/
│   ├── checkout/      ← Original session-event logs (events.csv)
│   ├── payment/       ← Raw payment transaction data (future)
│   └── receivables/   ← Raw invoice/AR data (future)
└── processed/
    ├── checkout/      ← Feature-engineered checkout datasets
    ├── payment/       ← Processed payment data
    └── receivables/   ← Processed receivables data
```

## Files

| File | Location | Description |
|---|---|---|
| `events.csv` | `raw/checkout/` | Session-event log used for checkout EDA and RF model training |

## Notes

- Do not commit large raw data files to version control.
- Paths are configured in `app/config/settings.py`.
- The notebook `notebooks/exploration/01_checkout_eda.ipynb` reads from `raw/checkout/events.csv`.
