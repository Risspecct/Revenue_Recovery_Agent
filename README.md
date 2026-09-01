# RazorPay Track 03 — Revenue Recovery Engine

**Objective:** Detect revenue at risk → determine the right intervention → execute a bounded recovery workflow.

---

## Revenue-Risk Domains

| Domain | Risk Signal | Primary Interventions |
|---|---|---|
| Payment failures | Failed transaction, retry history | PAYMENT_RETRY, ALTERNATE_PAYMENT_PROMPT, ESCALATE |
| Checkout abandonment | Abandoned cart + RF propensity score | CHECKOUT_REMINDER, INCENTIVIZED_RECOVERY |
| Overdue receivables | Days overdue, customer tier, invoice value | INVOICE_REMINDER, ESCALATE |

---

## ML Component

A Random Forest classifier (`ml/checkout/artifacts/selected_recovery_model.pkl`) provides checkout recovery propensity scores.

- Target: `recovered_within_7d`
- Features: `cart_additions`, `views`, `unique_products`, `event_count`, `duration_minutes`, `hour_of_day`, `day_of_week`
- Test ROC-AUC: 0.5954 | Top-10% lift: 1.61×
- Trained with scikit-learn 1.6.1

The score is a **prioritization signal only** — not a causal intervention-lift estimate.

---

## Architecture

```
Data / Risk Signals
    │
    ▼
app/decision/engine.py      ← deterministic decision engine
    │
    ├── rules.py            ← domain-specific rules (payment / checkout / receivable)
    ├── guardrails.py       ← safety & business constraints
    ├── schemas.py          ← RecoveryCase (input), DecisionResult (output)
    └── _catalogue.py       ← intervention catalogue + configurable thresholds
    │
    ▼
app/models/checkout_recovery.py   ← RF model wrapper
    │
    ▼
app/execution/executor.py   ← bounded action execution (placeholder)
    │
    ▼
app/services/recovery_service.py  ← orchestration (placeholder)
    │
    ▼
app/api/routes/recovery.py  ← FastAPI endpoints (placeholder)
```

---

## Repository Structure

```
razorpay-track03/
├── app/
│   ├── api/routes/recovery.py     ← FastAPI router (placeholder)
│   ├── config/settings.py         ← Centralized paths and settings
│   ├── decision/
│   │   ├── engine.py              ← Orchestrator: decide(case) → DecisionResult
│   │   ├── rules.py               ← Domain rule functions
│   │   ├── guardrails.py          ← Safety constraints
│   │   ├── schemas.py             ← RecoveryCase, DecisionResult, enums
│   │   └── _catalogue.py          ← Intervention catalogue + thresholds
│   ├── execution/executor.py      ← Execution layer (placeholder)
│   ├── models/checkout_recovery.py ← RF model wrapper
│   ├── services/recovery_service.py ← Service orchestration (placeholder)
│   └── main.py                    ← FastAPI entry point
├── data/
│   ├── raw/checkout/events.csv    ← Session-event log
│   └── processed/                 ← Generated datasets
├── ml/
│   └── checkout/artifacts/
│       └── selected_recovery_model.pkl
├── notebooks/
│   └── exploration/01_checkout_eda.ipynb
├── scripts/
│   └── evaluation/example_decisions.py
├── tests/
│   ├── decision/                  ← Engine + rule + guardrail tests (40 tests)
│   └── models/                    ← Model smoke tests (5 tests)
├── .env.example
├── requirements.txt
├── run.py
└── README.md
```

---

## Installation

```bash
pip install -r requirements.txt
```

If the scikit-learn version conflict causes model-loading warnings, the engine
falls back gracefully to the manually supplied `recovery_probability`.

---

## Running the Application

```bash
# Development server
uvicorn app.main:app --reload

# Or via run.py
python run.py
```

Health check: `GET http://localhost:8000/health`  
API docs: `http://localhost:8000/docs`

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Using the Decision Engine Directly

```python
from app.decision.schemas import CaseType, RecoveryCase
from app.decision.engine import decide

case = RecoveryCase(
    case_id="checkout_12345",
    case_type=CaseType.CHECKOUT_ABANDONMENT,
    customer_id="cust_9981",
    revenue_at_risk=850.0,
    recovery_probability=0.72,
    context={
        "cart_additions": 3, "views": 12, "unique_products": 4,
        "event_count": 25, "duration_minutes": 8.5,
        "hour_of_day": 14, "day_of_week": 2,
    },
)

result = decide(case)
print(result.to_dict())
```

See `scripts/evaluation/example_decisions.py` for more examples.

---

## ML Artifacts

| Artifact | Location |
|---|---|
| `selected_recovery_model.pkl` | `ml/checkout/artifacts/` |
| `baseline_recovery_model.pkl` | `ml/checkout/artifacts/` (future) |
| `feature_scaler.pkl` | `ml/checkout/artifacts/` (future) |

---

## Configurable Thresholds

All decision thresholds live in `app/decision/_catalogue.py → THRESHOLDS`.
Edit there to tune without touching rule logic.

---

## Assumptions & Limitations

- The RF model was serialized with sklearn 1.6.1; a version-mismatch warning may appear under newer sklearn. The loader suppresses this and falls back gracefully.
- The engine is stateless. Cooldown/deduplication state must be supplied by the caller via `case.context`.
- No causal intervention data exists. `recovery_probability` is a propensity signal only.
- FastAPI endpoints, execution layer, and service orchestration are placeholder stubs awaiting the next development phase.
