from __future__ import annotations

from typing import Any

from .agents import CaseContext, Specialist
from .analysis import analyze, decide
from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter
from .verification import verify_output


async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    """Collect scoped evidence, reconcile specialist findings and verify the decision."""
    context = CaseContext(case["case_id"], gateway, trace)
    order_agent = Specialist(
        "order-agent", frozenset({"get_order", "get_order_items", "get_sellers"})
    )
    payment_agent = Specialist(
        "payment-agent", frozenset({"get_payment_timeline", "get_refund_timeline"})
    )
    shipment_agent = Specialist("shipment-agent", frozenset({"get_shipment_summary"}))
    policy_agent = Specialist("policy-agent", frozenset({"get_policy"}))
    arguments = {"order_id": case["customer_request"]["claimed_order_id"]}
    order = await order_agent.collect(context, "get_order", **arguments)
    items = await order_agent.collect(context, "get_order_items", **arguments)
    payment = await payment_agent.collect(context, "get_payment_timeline", **arguments)
    shipment = await shipment_agent.collect(context, "get_shipment_summary", **arguments)
    policy = await policy_agent.collect(
        context, "get_policy", policy_version=case["policy_version"]
    )
    refund = None
    # The service returns tool errors for some absent refund histories. An error is
    # never converted to an empty authoritative timeline or cited as evidence.
    if any(
        claim["topic"].startswith("refund_") for claim in case["customer_request"].get("claims", [])
    ):
        try:
            refund = await payment_agent.collect(context, "get_refund_timeline", **arguments)
        except RuntimeError:
            context.emit(
                "handoff",
                "payment-agent",
                target="coordinator",
                decision_code="REFUND_EVIDENCE_UNAVAILABLE",
            )
    findings = analyze(
        case,
        order["data"],
        items["data"],
        payment["data"],
        shipment["data"],
        None if refund is None else refund["data"],
    )
    if "seller" in findings.domains:
        await order_agent.collect(context, "get_sellers", **arguments)
    if refund is None and any(
        claim["topic"].startswith("refund_") for claim in case["customer_request"].get("claims", [])
    ):
        findings.issue, findings.confidence = "insufficient_evidence", 0.3
    output = decide(case, findings, policy["data"], context.evidence)
    context.emit(
        "policy_decided",
        "policy-agent",
        target="verifier",
        decision_code=output["assessment"]["primary_issue"].upper(),
        evidence_refs=output["evidence_refs"],
    )
    context.emit("task_assigned", "coordinator", target="verifier", decision_code="VERIFY_OUTPUT")
    verify_output(output, case["case_id"], context.evidence, trace.contracts)
    context.emit(
        "verification_completed",
        "verifier",
        target="coordinator",
        decision_code="VERIFIED",
        evidence_refs=output["evidence_refs"],
    )
    # Keep raw evidence locally for review; it is never included in the submission ZIP.
    import json

    destination = trace.path.parent.parent / "evidence"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{case['case_id']}.json").write_text(
        json.dumps(context.evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output
