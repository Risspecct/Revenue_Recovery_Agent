# Razorpay Revenue Recovery Agent

## Razorpay AI Buildathon — Track 03

An AI-assisted revenue recovery agent that detects revenue at risk, determines the right intervention, validates it through guardrails, and executes a bounded recovery workflow across:

- Payment failures
- Checkout abandonment
- Overdue receivables

> **Detect → Predict → Decide → Explain → Guardrail → Execute → Measure**

---

## 1. Problem

Revenue leakage rarely occurs at a single point in the payment lifecycle.

A payment can fail, a customer can abandon checkout, or a B2B invoice can become overdue. Traditional analytics dashboards can surface these problems, while prediction models can estimate risk — but neither necessarily closes the loop.

Our goal is to build a system that moves from **identifying revenue at risk to taking a controlled recovery action**.

The agent therefore answers four questions:

1. **What revenue is at risk?**
2. **How likely is the case to require recovery?**
3. **What intervention should be taken?**
4. **Can that intervention be safely executed?**

---

## 2. Solution

The system follows a closed-loop recovery workflow:

```text
Revenue Signals
      ↓
Risk Detection
      ↓
ML + Domain Rules
      ↓
Decision Engine
      ↓
AI Analyst (Gemini)
      ↓
Guardrails
      ↓
Bounded Executor
      ↓
Outcome Measurement
````

Different revenue-risk sources are normalized into a common `RecoveryCase`.

The Decision Engine evaluates each case using ML signals, domain-specific rules, available interventions, and configured policies.

The resulting decision is then passed to the AI Analyst for explanation and customer-facing communication.

### Core design principle

**ML predicts. Rules decide. Guardrails authorize. The executor acts.**

The LLM is intentionally downstream of financial decisioning. Gemini cannot override the selected action or bypass recovery guardrails.

---

## 3. Revenue-Risk Domains

### Payment Failures

Payment failures are handled using deterministic recovery rules.

Supported interventions include:

* Payment retry
* Alternate payment prompt
* Safe fallback / no action

The available payment dataset does not provide suitable recovery-outcome labels for a supervised recovery model, so this domain currently relies on deterministic rules rather than forcing an unsuitable ML model.

### Checkout Abandonment

The checkout pipeline identifies abandoned sessions and uses behavioural signals to estimate recovery propensity.

The model uses features such as:

* Cart additions
* Product views
* Unique products
* Event count
* Session duration
* Hour of day
* Day of week

### Overdue Receivables

The O2C pipeline identifies open receivables and estimates late-payment risk using historical customer and invoice behaviour.

Potential interventions include:

* Invoice reminder
* Escalation
* No action

---

## 4. Data Preparation Pipeline

The project includes preparation scripts that transform raw datasets into the structured formats required by the ML models and recovery engine.

Raw source data is kept separate from application-ready datasets.

```text
Raw Dataset
     ↓
Cleaning
     ↓
Feature Engineering
     ↓
Sessionization / Customer History
     ↓
Outcome Construction
     ↓
Prepared Dataset
     ↓
Model Training / Inference
     ↓
Recovery Cases
```

### Checkout pipeline

Raw event-level checkout data is transformed into session-level records.

The preparation process:

* Groups behavioural events into sessions
* Identifies cart activity
* Generates behavioural features
* Identifies abandoned checkout sessions
* Applies a complete 7-day observation window
* Reconstructs historical recovery outcomes
* Produces model-ready data

Historical recovery is defined using a 7-day post-abandonment observation window and the project's transaction-to-session matching logic.

### O2C pipeline

The receivables preparation process:

* Cleans invoice records
* Normalizes customer and payment attributes
* Builds historical customer behaviour
* Prevents future-payment leakage
* Generates late-payment features
* Produces model-ready invoice records
* Feeds open receivables into the recovery scanner

This separation makes the data pipeline reproducible and prevents application logic from depending directly on raw source formats.

---

## 5. Machine Learning

### Checkout Recovery

The checkout model uses a Random Forest classifier.

Dataset processing produced:

* **2,756,101** events
* **1,407,580** visitors
* **1,761,675** sessionized sessions
* **43,924** cart sessions
* **30,618** abandoned sessions with a complete 7-day observation window
* **1,654** historically recovered sessions
* **5.40%** historical recovery rate

Model performance:

| Metric       | Result |
| ------------ | -----: |
| ROC-AUC      | 0.5954 |
| PR-AUC       | 0.0871 |
| Top-10% Lift |  1.61× |

The checkout model provides a **recovery propensity / prioritization signal**.

It is deliberately **not presented as a causal estimate of intervention uplift**.

### O2C Late-Payment Risk

The O2C model uses leakage-safe customer history to estimate late-payment risk.

Dataset:

* **48,839** cleaned invoices
* **9,681** open invoices scored

Model performance:

| Metric  | Result |
| ------- | -----: |
| ROC-AUC | 0.8282 |
| PR-AUC  | 0.7780 |

A validated O2C case produced a late-payment probability of **0.9776**, a risk score of **0.9075**, HIGH priority, and an approved `INVOICE_REMINDER` intervention.

---

## 6. Decision Engine

ML outputs are not directly converted into financial actions.

The Decision Engine combines:

* Case type
* Revenue at risk
* Recovery propensity / risk signals
* Domain-specific rules
* Available interventions
* Priority logic
* Guardrail policies

It produces a structured `DecisionResult` containing:

* Risk score
* Priority
* Recommended action
* Decision reason
* Confidence
* Guardrail status
* Revenue reasoning

Supported actions include:

```text
PAYMENT_RETRY
ALTERNATE_PAYMENT_PROMPT
CHECKOUT_REMINDER
INCENTIVIZED_RECOVERY
INVOICE_REMINDER
ESCALATE
NO_ACTION
```

This separation allows predictive models to evolve without allowing them to directly control recovery actions.

---

## 7. AI Analyst — Gemini

Google Gemini provides an additional reasoning and communication layer after the deterministic decision has been made.

For a reviewed case, the AI Analyst provides:

* Explanation of why the case matters
* Explanation of the selected intervention
* Customer-facing recovery communication

Example flow:

```text
Recovery Case
     ↓
Decision Engine
     ↓
Recommended Action
     ↓
Gemini Analyst
     ├── Decision Explanation
     └── Customer Message
```

The LLM is **advisory**.

It cannot:

* Change the recommended action
* Bypass guardrails
* Authorize an unapproved intervention
* Claim that revenue has been recovered

---

## 8. Guardrails & Bounded Execution

Before any action can execute, it passes through configured recovery policies.

Examples include:

* Payment retry limits
* Successful-payment protection
* Paid-invoice protection
* Intervention availability checks
* Checkout eligibility
* Recovery cooldowns
* Safe fallbacks

Actions can therefore be:

* **APPROVED**
* **BLOCKED**
* **ESCALATED**
* **NO_ACTION**

The executor only performs actions that are permitted by the decision and guardrail layers.

The current prototype uses **simulated execution**. Execution results are explicitly marked as simulated and are not represented as proof of successful payment or recovered revenue.

---

## 9. Historical Recovery Measurement

The system includes a historical replay mechanism for checkout recovery.

The replay reconstructs the same 7-day recovery target used during model preparation.

Result:

**1,654 recovered sessions / 30,618 observable abandoned sessions = 5.40%**

An important design choice is that the system does **not fabricate monetary recovery**.

The public checkout dataset contains recovery events but does not provide transaction monetary values. Therefore, the system reports historical recovered cases rather than inventing recovered revenue.

Similarly, simulated execution is never counted as actual recovered money.

Where monetary information is available, such as O2C invoice data, revenue-at-risk is measured directly from the source.

---

## 10. Frontend

The Streamlit frontend provides a compact revenue-recovery work queue rather than a traditional analytics dashboard.

It allows an operator to:

* Scan for revenue at risk
* View prioritized cases
* Filter and search cases
* Sort by priority, revenue at risk, or risk score
* Review case-level risk
* Inspect the recommended intervention
* View guardrail status
* Read the Gemini AI Analyst explanation
* Review the generated customer message
* Execute an approved recovery action
* Inspect the simulated execution result

The interface is designed around the operational recovery workflow rather than historical reporting.

---

## 11. Why This Is Not Just a Prediction Model

A conventional prediction system might answer:

> **"Which customers or transactions are risky?"**

Our system continues beyond prediction:

```text
Risk
 ↓
Decision
 ↓
Policy Validation
 ↓
Action
 ↓
Execution
 ↓
Measurement
```

The ML model is therefore one component of the recovery agent, rather than the entire product.

---

## 12. Why This Is Not Just a Dashboard

A dashboard primarily reports information.

The Revenue Recovery Agent creates a structured recovery case and moves it through an operational workflow:

**Detect → Decide → Explain → Guardrail → Execute**

The Streamlit work queue is the interface to this workflow.

The core product is the **closed-loop recovery system behind the interface**.

---

## 13. Project Structure

```text
.
├── app/
│   ├── api/
│   │   ├── models.py
│   │   └── routes/
│   │
│   ├── config/
│   │   └── settings.py
│   │
│   ├── decision/
│   │   ├── engine.py
│   │   ├── schemas.py
│   │   └── rules/
│   │
│   ├── execution/
│   │   └── executor.py
│   │
│   ├── models/
│   │   ├── checkout_recovery.py
│   │   └── o2c.py
│   │
│   └── services/
│       ├── revenue_scanner.py
│       ├── recovery_service.py
│       ├── batch_recovery.py
│       └── llm_analyst.py
│
├── ml/
│   ├── checkout/
│   │   └── artifacts/
│   │
│   └── o2c/
│       └── artifacts/
│
├── scripts/
│   └── data preparation and ML pipeline scripts
│
├── data/
│   ├── raw/
│   │   ├── checkout/
│   │   ├── payment/
│   │   └── receivables/
│   │
│   ├── processed/
│   │   └── checkout/
│   │
│   └── prepared/
│
├── tests/
│
├── streamlit_app.py
├── requirements.txt
└── README.md
```

---

## 14. API

Key recovery endpoints:

```text
GET  /health

POST /api/recovery/evaluate

POST /api/recovery/execute

POST /api/recovery/scan

GET  /api/recovery/cases

POST /api/recovery/execute/{case_id}

GET  /api/recovery/batch-results

GET  /api/recovery/analyze/{case_id}
```

---

## 15. Technology Stack

| Layer           | Technology      |
| --------------- | --------------- |
| Backend         | Python, FastAPI |
| Frontend        | Streamlit       |
| ML              | scikit-learn    |
| Data Processing | pandas, NumPy   |
| Model Artifacts | joblib          |
| AI Analyst      | Google Gemini   |
| Testing         | pytest          |

---

## 16. Running Locally

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure Gemini

Create a `.env` file:

```env
GEMINI_API_KEY=your_key_here
```

### Start the backend

```bash
uvicorn app.main:app --reload
```

### Start the frontend

In another terminal:

```bash
streamlit run streamlit_app.py
```

---

## 17. Demo Flow

The intended demonstration follows the complete recovery lifecycle:

```text
Scan for Revenue at Risk
          ↓
Prioritized Work Queue
          ↓
Review Case
          ↓
Risk Assessment
          ↓
Agent Decision
          ↓
AI Analyst Explanation
          ↓
Guardrail Verification
          ↓
Execute Recovery Action
          ↓
Execution Result
          ↓
Historical Recovery Measurement
```

---

## 18. Design Principles

### ML predicts; deterministic policy decides

Predictive models provide risk signals. Business rules determine what intervention is appropriate.

### LLM explains; it does not authorize

Gemini provides contextual reasoning and customer communication without controlling financial actions.

### Guardrails come before execution

Every action must pass configured recovery policies.

### Execution is bounded

The executor can only perform actions represented by the approved recovery action catalogue.

### Measurement is evidence-based

Predictions and simulated executions are never presented as guaranteed or realized revenue recovery.

### Data limitations are explicit

When source data does not contain monetary outcomes, the system reports the limitation rather than manufacturing a financial metric.

---

## Core Objective

Build an agent that **detects revenue at risk, determines the right intervention, and executes a bounded recovery workflow** across payment failures, checkout abandonment, and overdue receivables.

The objective is not merely to predict revenue loss.

It is to **close the loop from revenue-risk detection to controlled recovery action and measurable outcome**.
