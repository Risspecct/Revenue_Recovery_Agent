"""
API integration tests for the Recovery Decision Engine FastAPI layer.
Uses FastAPI TestClient -- no live server required.
Full stack: HTTP -> route -> service -> engine -> response.
"""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.decision.schemas import GuardrailStatus, Intervention

client = TestClient(app)

_PAY = {"case_id":"pay_api_001","case_type":"PAYMENT_FAILURE","customer_id":"c","revenue_at_risk":6000.0,"context":{"failure_reason":"network_error","retry_count":1}}
_CHK = {"case_id":"chk_api_001","case_type":"CHECKOUT_ABANDONMENT","customer_id":"c","revenue_at_risk":4000.0,"recovery_probability":0.72,"context":{}}
_REC = {"case_id":"rec_api_001","case_type":"OVERDUE_RECEIVABLE","customer_id":"c","revenue_at_risk":3500.0,"context":{"payment_status":"overdue","days_overdue":14,"days_since_last_reminder":10}}

FIELDS = {"case_id","case_type","revenue_at_risk","recovery_probability","risk_score","priority","recommended_action","reason","confidence","guardrail_status","revenue_reasoning"}

def test_health(): assert client.get("/health").status_code == 200
def test_health_shape():
    b = client.get("/health").json(); assert b["status"]=="ok"; assert "version" in b

def test_all_fields_present():
    b = client.post("/api/recovery/evaluate",json=_CHK).json()
    for f in FIELDS: assert f in b, f"Missing {f}"
def test_enum_fields_are_strings():
    b = client.post("/api/recovery/evaluate",json=_CHK).json()
    assert isinstance(b["case_type"],str); assert isinstance(b["priority"],str)
    assert isinstance(b["recommended_action"],str); assert isinstance(b["guardrail_status"],str)
def test_numeric_fields():
    b = client.post("/api/recovery/evaluate",json=_CHK).json()
    for f in ("revenue_at_risk","recovery_probability","risk_score","confidence"):
        assert isinstance(b[f],(int,float)), f
def test_revenue_reasoning_is_dict():
    assert isinstance(client.post("/api/recovery/evaluate",json=_CHK).json()["revenue_reasoning"],dict)

def test_payment_retry():
    b = client.post("/api/recovery/evaluate",json=_PAY).json()
    assert b["recommended_action"]=="PAYMENT_RETRY"; assert b["guardrail_status"]=="APPROVED"
def test_payment_succeeded_no_action():
    p={**_PAY,"case_id":"p2","context":{"payment_succeeded":True}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="NO_ACTION"
def test_payment_retry_exhausted_escalate():
    p={**_PAY,"case_id":"p3","revenue_at_risk":7000.0,"context":{"failure_reason":"timeout","retry_count":3}}
    b=client.post("/api/recovery/evaluate",json=p).json()
    assert b["recommended_action"]=="ESCALATE"; assert b["guardrail_status"]=="ESCALATED"
def test_payment_retry_exhausted_high_priority():
    p={**_PAY,"case_id":"p4","revenue_at_risk":7000.0,"context":{"failure_reason":"timeout","retry_count":3}}
    assert client.post("/api/recovery/evaluate",json=p).json()["priority"]=="HIGH"
def test_payment_card_declined_alternate():
    p={**_PAY,"case_id":"p5","revenue_at_risk":2000.0,"context":{"failure_reason":"card_declined","retry_count":0}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="ALTERNATE_PAYMENT_PROMPT"

def test_checkout_reminder():
    b=client.post("/api/recovery/evaluate",json=_CHK).json()
    assert b["recommended_action"]=="CHECKOUT_REMINDER"; assert b["guardrail_status"]=="APPROVED"; assert b["priority"]=="HIGH"
def test_checkout_already_recovered():
    p={**_CHK,"case_id":"c2","context":{"already_recovered":True}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="NO_ACTION"
def test_checkout_incentivized():
    p={**_CHK,"case_id":"c3","revenue_at_risk":2500.0,"recovery_probability":0.55,"context":{"incentive_eligible":True}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="INCENTIVIZED_RECOVERY"
def test_checkout_low_propensity_no_action():
    p={**_CHK,"case_id":"c4","revenue_at_risk":50.0,"recovery_probability":0.04,"context":{}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="NO_ACTION"
def test_checkout_prob_in_range():
    prob=client.post("/api/recovery/evaluate",json=_CHK).json()["recovery_probability"]
    assert 0.0<=prob<=1.0

def test_receivable_reminder():
    b=client.post("/api/recovery/evaluate",json=_REC).json()
    assert b["recommended_action"]=="INVOICE_REMINDER"; assert b["guardrail_status"]=="APPROVED"
def test_receivable_paid_no_action():
    p={**_REC,"case_id":"r2","context":{"payment_status":"paid"}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="NO_ACTION"
def test_receivable_severely_overdue_escalate():
    p={**_REC,"case_id":"r3","context":{"payment_status":"overdue","days_overdue":75}}
    b=client.post("/api/recovery/evaluate",json=p).json()
    assert b["recommended_action"]=="ESCALATE"; assert b["guardrail_status"]=="ESCALATED"
def test_receivable_priority_account_escalate():
    p={**_REC,"case_id":"r4","context":{"payment_status":"overdue","days_overdue":5,"is_priority_account":True}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="ESCALATE"
def test_receivable_cooldown_no_reminder():
    p={**_REC,"case_id":"r5","context":{"payment_status":"overdue","days_overdue":10,"days_since_last_reminder":2}}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="NO_ACTION"

def test_whitelist_allows():
    p={**_PAY,"case_id":"w1","available_interventions":["PAYMENT_RETRY","ESCALATE"]}
    assert client.post("/api/recovery/evaluate",json=p).json()["recommended_action"]=="PAYMENT_RETRY"
def test_whitelist_blocks_and_names_action():
    p={**_CHK,"case_id":"w2","available_interventions":["NO_ACTION"]}
    b=client.post("/api/recovery/evaluate",json=p).json()
    assert b["recommended_action"]=="NO_ACTION"; assert "CHECKOUT_REMINDER" in b["reason"]
def test_whitelist_deduplication():
    p={**_PAY,"case_id":"w3","available_interventions":["PAYMENT_RETRY","PAYMENT_RETRY","ESCALATE"]}
    assert client.post("/api/recovery/evaluate",json=p).status_code==200

def test_propensity_weighted_value_present():
    assert "propensity_weighted_recovery_value" in client.post("/api/recovery/evaluate",json=_CHK).json()["revenue_reasoning"]
def test_propensity_weighted_value_correct():
    p={**_CHK,"case_id":"rr1","revenue_at_risk":1000.0,"recovery_probability":0.50,"context":{}}
    v=client.post("/api/recovery/evaluate",json=p).json()["revenue_reasoning"]["propensity_weighted_recovery_value"]
    assert abs(v-500.0)<0.01
def test_no_hypothetical_without_assumption():
    assert "hypothetical_intervention_value" not in client.post("/api/recovery/evaluate",json=_CHK).json()["revenue_reasoning"]
def test_note_does_not_claim_guaranteed():
    note=client.post("/api/recovery/evaluate",json=_CHK).json()["revenue_reasoning"].get("note","")
    assert "not guaranteed" in note.lower() or "propensity-weighted" in note.lower()

def test_missing_case_id_422():
    p={k:v for k,v in _CHK.items() if k!="case_id"}
    assert client.post("/api/recovery/evaluate",json=p).status_code==422
def test_negative_revenue_422():
    assert client.post("/api/recovery/evaluate",json={**_CHK,"case_id":"v1","revenue_at_risk":-1.0}).status_code==422
def test_prob_above_1_422():
    assert client.post("/api/recovery/evaluate",json={**_CHK,"case_id":"v2","recovery_probability":1.5}).status_code==422
def test_invalid_case_type_422():
    assert client.post("/api/recovery/evaluate",json={**_CHK,"case_id":"v3","case_type":"NOPE"}).status_code==422
def test_invalid_intervention_422():
    assert client.post("/api/recovery/evaluate",json={**_CHK,"case_id":"v4","available_interventions":["NOPE"]}).status_code==422
def test_whitespace_case_id_422():
    assert client.post("/api/recovery/evaluate",json={**_CHK,"case_id":"   "}).status_code==422
def test_zero_revenue_ok():
    assert client.post("/api/recovery/evaluate",json={**_CHK,"case_id":"v5","revenue_at_risk":0.0}).status_code==200
def test_empty_context_ok():
    assert client.post("/api/recovery/evaluate",json={**_PAY,"case_id":"v6","context":{}}).status_code==200

def test_determinism():
    b1=client.post("/api/recovery/evaluate",json=_CHK).json()
    b2=client.post("/api/recovery/evaluate",json=_CHK).json()
    assert b1["recommended_action"]==b2["recommended_action"]
    assert b1["risk_score"]==b2["risk_score"]
    assert b1["guardrail_status"]==b2["guardrail_status"]

def test_approved_status():
    assert client.post("/api/recovery/evaluate",json=_CHK).json()["guardrail_status"]=="APPROVED"
def test_escalated_status():
    p={**_REC,"case_id":"gs1","context":{"payment_status":"overdue","days_overdue":80}}
    b=client.post("/api/recovery/evaluate",json=p).json()
    assert b["recommended_action"]=="ESCALATE"; assert b["guardrail_status"]=="ESCALATED"
def test_guardrail_status_valid_values():
    valid={"APPROVED","BLOCKED","ESCALATED"}
    for payload in [_PAY,_CHK,_REC]:
        b=client.post("/api/recovery/evaluate",json=payload).json()
        assert b["guardrail_status"] in valid
