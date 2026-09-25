"""Checks that do not depend on hidden scoring rules."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .contracts import Contracts


def verify_output(
    output: dict[str, Any],
    case_id: str,
    evidence: list[dict[str, Any]],
    contracts: Contracts,
) -> None:
    contracts.validate_output(output, f"outputs/{case_id}.json")
    if output["case_id"] != case_id:
        raise ValueError("Output case_id differs from the active case")
    available = {item["evidence_ref"] for item in evidence}
    cited = set(output["evidence_refs"])
    if not cited or not cited <= available:
        raise ValueError("Output must cite evidence acquired for this case")
    for claim in output.get("claim_assessments", []):
        if not set(claim["evidence_refs"]) <= cited:
            raise ValueError("Claim evidence must be included in output evidence")
    money = output["financial_resolution"]
    total = sum((Decimal(str(line["amount_brl"])) for line in money["refund_lines"]), Decimal(0))
    if total != Decimal(str(money["recommended_refund_brl"])):
        raise ValueError("Refund total differs from the sum of refund lines")
    if money["recommended_refund_brl"] > 0 and output["assessment"]["case_status"] == "no_action":
        raise ValueError("A positive refund cannot have no_action status")
    ranks = [cause["rank"] for cause in output["root_cause_analysis"]["ranked_causes"]]
    if ranks != list(range(1, len(ranks) + 1)):
        raise ValueError("Root causes must have consecutive unique ranks")
