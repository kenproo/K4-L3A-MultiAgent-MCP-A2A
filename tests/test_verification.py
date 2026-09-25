from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from student_agent.contracts import Contracts
from student_agent.verification import verify_output


@pytest.fixture
def sample():
    ref = "ev_" + "synthetic_test_only_123456"
    return {
        "schema_version": "day09-l3a-output-v2",
        "case_id": "TEST_CASE",
        "assessment": {
            "primary_issue": "canceled_order_paid",
            "case_status": "action_required",
            "confidence": 0.9,
        },
        "affected_entities": {
            "order_ids": ["test-order"],
            "item_ids": [],
            "seller_ids": [],
            "payment_references": [],
            "shipment_ids": [],
        },
        "root_cause_analysis": {"ranked_causes": [], "responsible_parties": []},
        "evidence_refs": [ref],
        "data_conflicts": [],
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": 0.3,
            "refund_lines": [
                {"reason_code": "TEST", "amount_brl": 0.1, "entity_id": None},
                {"reason_code": "TEST", "amount_brl": 0.2, "entity_id": None},
            ],
        },
        "resolution_actions": ["TEST_ACTION"],
    }


def verify(value, evidence=None, case_id="TEST_CASE"):
    contracts = Contracts(Path(__file__).resolve().parents[1] / "contracts" / "schemas")
    if evidence is None:
        evidence = [{"evidence_ref": value["evidence_refs"][0]}]
    verify_output(value, case_id, evidence, contracts)


def test_decimal_refund_total(sample):
    verify(sample)


def test_wrong_case_rejected(sample):
    with pytest.raises(ValueError, match="case_id"):
        verify(sample, case_id="OTHER_CASE")


def test_unknown_evidence_rejected(sample):
    with pytest.raises(ValueError, match="acquired"):
        verify(sample, evidence=[])


def test_inconsistent_money_rejected(sample):
    sample["financial_resolution"]["recommended_refund_brl"] = 0.4
    with pytest.raises(ValueError, match="sum"):
        verify(sample)


def test_refund_no_action_rejected(sample):
    sample["assessment"]["case_status"] = "no_action"
    with pytest.raises(ValueError, match="no_action"):
        verify(sample)


def test_claim_ref_must_be_cited(sample):
    sample = deepcopy(sample)
    sample["claim_assessments"] = [
        {
            "claim_id": "claim-test",
            "verdict": "supported",
            "confidence": 0.9,
            "evidence_refs": ["ev_" + "z" * 24],
        }
    ]
    with pytest.raises(ValueError, match="Claim evidence"):
        verify(sample)
