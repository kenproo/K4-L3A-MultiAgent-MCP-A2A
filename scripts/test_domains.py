import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from student_agent.analysis import Findings, money, moment

sys.stdout.reconfigure(encoding="utf-8")

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

inputs = sorted(Path("inputs").glob("*.json"))
ev_dir = Path(".local/runs/4966a62547f94efca9c5a00f066bd323/evidence")

print(f"Testing {len(inputs)} cases...")

summary = {}
for inp_path in inputs:
    case_id = inp_path.stem
    case = json.loads(inp_path.read_text(encoding="utf-8"))
    ev = json.loads((ev_dir / f"{case_id}.json").read_text(encoding="utf-8"))
    
    # Extract data by domain
    by_dom = {}
    for item in ev:
        by_dom[item["domain"]] = item
    
    # Simulate analyze
    # Check issue from existing output
    out = json.loads(Path(f"outputs/{case_id}.json").read_text(encoding="utf-8"))
    issue = out["assessment"]["primary_issue"]
    
    # Determine domains
    if issue == "unsupported_claim":
        msg = case.get("customer_request", {}).get("message", "")
        if "giao nhận" in msg:
            doms = {"order", "shipment", "item", "policy"}
        else:
            doms = {"order", "shipment", "payment", "policy"}
    else:
        doms = ISSUE_DOMAINS[issue]
    
    # Check if all required domains are in acquired evidence
    acquired_doms = set(by_dom.keys())
    assert doms <= acquired_doms, f"Case {case_id} missing domains: {doms - acquired_doms}"
    
    summary.setdefault((issue, tuple(sorted(doms))), []).append(case_id)

for (issue, doms), cases in sorted(summary.items()):
    print(f"{issue:24s} | {len(cases):2d} cases | domains: {doms}")

print("All cases successfully verified!")
