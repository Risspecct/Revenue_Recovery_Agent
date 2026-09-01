"""
Example inputs and outputs for the Recovery Decision Engine.

Run from the repository root:
    python scripts/evaluation/example_decisions.py
"""

import json
from app.decision.schemas import CaseType, RecoveryCase
from app.decision.engine import decide

cases = [
    # --- Payment failures ---------------------------------------------------
    RecoveryCase(
        case_id="pay_hv_retry",
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust_001",
        revenue_at_risk=8_000.0,
        context={"failure_reason": "network_error", "retry_count": 1},
    ),
    RecoveryCase(
        case_id="pay_succeeded",
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust_002",
        revenue_at_risk=5_000.0,
        context={"payment_succeeded": True},
    ),
    RecoveryCase(
        case_id="pay_retry_exhausted",
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust_003",
        revenue_at_risk=6_500.0,
        context={"failure_reason": "timeout", "retry_count": 3},
    ),
    RecoveryCase(
        case_id="pay_low_value",
        case_type=CaseType.PAYMENT_FAILURE,
        customer_id="cust_004",
        revenue_at_risk=150.0,
        context={"failure_reason": "unknown_xyz", "retry_count": 0},
    ),
    # --- Checkout abandonment ----------------------------------------------
    RecoveryCase(
        case_id="chk_hv_high_prop",
        case_type=CaseType.CHECKOUT_ABANDONMENT,
        customer_id="cust_005",
        revenue_at_risk=4_200.0,
        recovery_probability=0.0,
        context={
            "cart_additions": 4, "views": 18, "unique_products": 5,
            "event_count": 32, "duration_minutes": 11.0,
            "hour_of_day": 15, "day_of_week": 3,
        },
    ),
    RecoveryCase(
        case_id="chk_low_prop",
        case_type=CaseType.CHECKOUT_ABANDONMENT,
        customer_id="cust_006",
        revenue_at_risk=90.0,
        recovery_probability=0.04,
        context={},
    ),
    RecoveryCase(
        case_id="chk_incentive_eligible",
        case_type=CaseType.CHECKOUT_ABANDONMENT,
        customer_id="cust_008",
        revenue_at_risk=2_500.0,
        recovery_probability=0.55,
        context={"incentive_eligible": True},
    ),
    # --- Overdue receivables -----------------------------------------------
    RecoveryCase(
        case_id="rec_normal",
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id="cust_010",
        revenue_at_risk=3_500.0,
        context={"payment_status": "overdue", "days_overdue": 14, "days_since_last_reminder": 10},
    ),
    RecoveryCase(
        case_id="rec_paid",
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id="cust_011",
        revenue_at_risk=4_000.0,
        context={"payment_status": "paid"},
    ),
    RecoveryCase(
        case_id="rec_severely_overdue",
        case_type=CaseType.OVERDUE_RECEIVABLE,
        customer_id="cust_012",
        revenue_at_risk=2_000.0,
        context={"payment_status": "overdue", "days_overdue": 75},
    ),
]

if __name__ == "__main__":
    for case in cases:
        result = decide(case)
        print(json.dumps(result.to_dict(), indent=2))
        print("-" * 60)
