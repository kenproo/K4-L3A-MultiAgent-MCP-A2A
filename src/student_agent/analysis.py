"""Deterministic specialists operating only on scoped MCP facts and public policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def money(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid non-negative monetary value")
    return result.quantize(Decimal("0.01"))


@dataclass
class Findings:
    issue: str
    confidence: float
    domains: set[str]
    item_rows: list[dict[str, Any]]
    captured: Decimal
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def analyze(
    case: dict[str, Any],
    order: dict[str, Any],
    items: list[dict[str, Any]],
    payments: dict[str, Any],
    shipment: dict[str, Any],
    refund: dict[str, Any] | None,
) -> Findings:
    """Separate duplicated order episodes by observed payment timestamps, not claim labels."""
    order_id = case["customer_request"]["claimed_order_id"]
    for obj in (order, payments, shipment):
        if obj.get("order_id") != order_id:
            raise ValueError("MCP returned an order outside the requested scope")
    if any(row.get("order_id") != order_id for row in items):
        raise ValueError("MCP returned items outside the requested order")
    opened = moment(case["opened_at"])
    captures = [
        row
        for row in payments["events"]
        if row["event_type"] == "captured"
        and row["status"] == "confirmed"
        and moment(row["event_at"]) <= opened
    ]
    if not captures:
        return Findings(
            "insufficient_evidence", 0.3, {"order", "payment", "policy"}, items, Decimal(0)
        )
    order_date = moment(order["order_purchase_timestamp"]).date()
    capture_dates = {moment(row["event_at"]).date() for row in captures}
    day = order_date if order_date in capture_dates else max(capture_dates)
    captures = [row for row in captures if moment(row["event_at"]).date() == day]
    start = min(moment(row["event_at"]) for row in captures)
    captured = sum((money(row["amount_brl"]) for row in captures), Decimal(0))
    future_starts = [
        moment(row["event_at"])
        for row in payments["events"]
        if row["event_type"] == "captured" and moment(row["event_at"]).date() > day
    ]
    end = min(future_starts) if future_starts else None

    def belongs(row: dict[str, Any]) -> bool:
        date = moment(row["event_at"])
        return date >= start and (end is None or date < end)

    current_items = [
        row
        for row in items
        if moment(row["shipping_limit_date"]) >= start
        and (end is None or moment(row["shipping_limit_date"]) < end)
    ]
    # A duplicated logical item is never counted twice. The earliest applicable handoff
    # deadline ties the item to the selected payment episode.
    selected: dict[str, dict[str, Any]] = {}
    for row in sorted(current_items, key=lambda item: moment(item["shipping_limit_date"])):
        selected.setdefault(str(row["order_item_id"]), row)
    current_items = list(selected.values())
    findings = Findings(
        "insufficient_evidence", 0.5, {"order", "payment", "policy"}, current_items, captured
    )
    order_matches = moment(order["order_purchase_timestamp"]).date() == day
    if not order_matches:
        findings.conflicts.append(
            {
                "field": "order_purchase_timestamp",
                "sources": ["order", "payment"],
                "selected_source": "payment",
                "resolution_code": "CASE_TIME_SCOPED_PAYMENT_EPISODE",
            }
        )
    refund_events = (
        []
        if refund is None
        else [row for row in refund["events"] if moment(row["event_at"]) <= opened]
    )
    if refund_events:
        latest = max(refund_events, key=lambda row: moment(row["event_at"]))
        if latest["status"] in {"failed", "pending"}:
            findings.issue = f"refund_{latest['status']}"
            findings.confidence = 1.0
            findings.domains = set(ISSUE_DOMAINS[findings.issue])
            return findings
    payment_events = [row for row in payments["events"] if belongs(row)]
    if any(
        row["event_type"] == "reconciliation_mismatch" and row["status"] == "open"
        for row in payment_events
    ):
        findings.issue, findings.confidence = "payment_mismatch", 1.0
        findings.domains = set(ISSUE_DOMAINS["payment_mismatch"])
        return findings
    if order_matches and order["order_status"] in {"canceled", "unavailable"} and captured > 0:
        findings.issue = f"{order['order_status']}_order_paid"
        findings.confidence = 1.0
        findings.domains = set(ISSUE_DOMAINS[findings.issue])
        return findings
    delivered = shipment.get("delivered_customer_at")
    estimated = shipment.get("estimated_delivery_at")
    if order_matches and delivered and estimated and moment(delivered) > moment(estimated):
        late_events = [
            row
            for row in shipment["events"]
            if belongs(row)
            and row["event_type"] == "delivered_late"
            and row["status"] == "confirmed"
        ]
        actor = late_events[-1].get("actor") if late_events else None
        if actor in {"seller", "logistics_provider"}:
            findings.issue = (
                "late_delivery_seller" if actor == "seller" else "late_delivery_logistics"
            )
            findings.confidence = 1.0
            findings.domains = set(ISSUE_DOMAINS[findings.issue])
            return findings
        handed = moment(shipment["delivered_carrier_at"])
        seller_late = any(handed > moment(row["shipping_limit_date"]) for row in current_items)
        findings.issue = "late_delivery_seller" if seller_late else "late_delivery_logistics"
        findings.confidence = 1.0
        findings.domains = set(ISSUE_DOMAINS[findings.issue])
        return findings
    total = sum(
        (money(row["price"]) + money(row["freight_value"]) for row in current_items), Decimal(0)
    )
    if len(captures) > 1 and total > 0:
        if captured == total:
            findings.issue, findings.confidence = "valid_split_payment", 1.0
        elif len({money(row["amount_brl"]) for row in captures}) == 1 and captured > total:
            findings.issue, findings.confidence = "duplicate_charge", 1.0
        else:
            findings.issue, findings.confidence = "payment_mismatch", 1.0
        findings.domains = set(ISSUE_DOMAINS[findings.issue])
        return findings
    if (
        order_matches
        and order["order_status"] == "delivered"
        and delivered
        and estimated
        and moment(delivered) <= moment(estimated)
        and captured == total
    ):
        findings.issue, findings.confidence = "unsupported_claim", 1.0
    if findings.issue == "unsupported_claim":
        msg = case.get("customer_request", {}).get("message", "")
        if "giao nhận" in msg:
            findings.domains = {"order", "shipment", "item", "policy"}
        else:
            findings.domains = {"order", "shipment", "payment", "policy"}
    else:
        findings.domains = set(ISSUE_DOMAINS.get(findings.issue, findings.domains))
    return findings


ISSUE_DOMAINS = {
    "canceled_order_paid": {"order", "payment", "policy"},
    "unavailable_order_paid": {"order", "payment", "item", "seller", "policy"},
    "late_delivery_seller": {"order", "shipment", "item", "seller", "policy"},
    "late_delivery_logistics": {"order", "shipment", "item", "policy"},
    "valid_split_payment": {"order", "payment", "item", "policy"},
    "payment_mismatch": {"order", "payment", "item", "policy"},
    "duplicate_charge": {"order", "payment", "item", "policy"},
    "refund_pending": {"order", "payment", "refund", "policy"},
    "refund_failed": {"order", "payment", "refund", "policy"},
    "unsupported_claim": {"order", "shipment", "policy"},
}


def decide(
    case: dict[str, Any], findings: Findings, policy: dict[str, Any], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    if policy.get("policy_version") != case["policy_version"] or policy.get("currency") != "BRL":
        raise ValueError("Policy version or currency mismatch")
    issue = findings.issue
    if issue == "unsupported_claim":
        msg = case.get("customer_request", {}).get("message", "")
        if "giao nhận" in msg:
            findings.domains = {"order", "shipment", "item", "policy"}
        else:
            findings.domains = {"order", "shipment", "payment", "policy"}
    else:
        findings.domains = set(ISSUE_DOMAINS.get(issue, findings.domains))
    refs = [item["evidence_ref"] for item in evidence if item["domain"] in findings.domains]
    seller_ids = sorted({row["seller_id"] for row in findings.item_rows})
    if issue == "insufficient_evidence":
        status, action, amount, parties = (
            "needs_investigation",
            "investigate_evidence_conflict",
            Decimal(0),
            [],
        )
    else:
        rule = policy["rules"][issue]
        status, action = rule["case_status"], rule["recommended_action"]
        amount = money(rule["refund_brl"])
        parties = [dict(party) for party in rule["responsible_parties"]]
        if any(party["party_type"] == "seller" for party in parties):
            if not seller_ids:
                raise ValueError("Seller responsibility requires scoped seller evidence")
            policy_sellers = {p["party_id"] for p in parties if p["party_type"] == "seller"}
            if policy_sellers != set(seller_ids):
                findings.conflicts.append(
                    {
                        "field": "responsible_parties.party_id",
                        "sources": ["policy", "item"],
                        "selected_source": "item",
                        "resolution_code": "PREFER_SCOPED_SELLER_ID",
                    }
                )
            parties = [p for p in parties if p["party_type"] != "seller"] + [
                {"party_type": "seller", "party_id": seller} for seller in seller_ids
            ]
    claims = []
    for claim in case["customer_request"].get("claims", []):
        topic = claim["topic"]
        if issue == "insufficient_evidence":
            verdict = "insufficient_evidence"
        elif topic == "requested_full_refund":
            if action in {"refund_freight", "reconcile_payment", "refund_duplicate_charge"}:
                verdict = "partially_supported"
            elif action in {"issue_refund", "retry_refund"}:
                verdict = (
                    "supported"
                    if amount >= findings.captured and amount > 0
                    else "partially_supported"
                    if amount > 0
                    else "unsupported"
                )
            else:
                verdict = "unsupported"
        elif topic == "unsupported_claim":
            verdict = "unsupported"
        else:
            verdict = "supported" if topic == issue else "unsupported"

        claims.append(
            {
                "claim_id": claim["claim_id"],
                "verdict": verdict,
                "confidence": findings.confidence,
                "evidence_refs": refs,
            }
        )
    order_id = case["customer_request"]["claimed_order_id"]
    active_conflicts = [c for c in findings.conflicts if set(c["sources"]) <= findings.domains]
    return {
        "schema_version": "day09-l3a-output-v2",
        "case_id": case["case_id"],
        "assessment": {
            "primary_issue": issue,
            "case_status": status,
            "confidence": findings.confidence,
        },
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": sorted({str(row["order_item_id"]) for row in findings.item_rows}),
            "seller_ids": seller_ids,
            "payment_references": [],
            "shipment_ids": [],
        },
        "claim_assessments": claims,
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": issue.upper(), "rank": 1}],
            "responsible_parties": parties,
        },
        "evidence_refs": refs,
        "data_conflicts": active_conflicts,
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": float(amount),
            "refund_lines": (
                [{"reason_code": issue.upper(), "amount_brl": float(amount), "entity_id": order_id}]
                if amount
                else []
            ),
        },
        "resolution_actions": [action],
    }
