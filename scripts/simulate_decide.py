import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from student_agent.analysis import analyze, decide
from student_agent.contracts import Contracts
from student_agent.verification import verify_output

sys.stdout.reconfigure(encoding="utf-8")

root = Path(__file__).resolve().parents[1]
contracts = Contracts(root / "contracts" / "schemas")

inputs = sorted(Path("inputs").glob("*.json"))
ev_dir = Path(".local/runs/4966a62547f94efca9c5a00f066bd323/evidence")

print(f"Simulating decide() for all {len(inputs)} cases...")

issues = {}
for inp_path in inputs:
    case_id = inp_path.stem
    case = json.loads(inp_path.read_text(encoding="utf-8"))
    ev = json.loads((ev_dir / f"{case_id}.json").read_text(encoding="utf-8"))
    
    by_dom = {item["domain"]: item for item in ev}
    order = by_dom["order"]
    items = by_dom["item"]
    payment = by_dom["payment"]
    shipment = by_dom["shipment"]
    policy = by_dom["policy"]
    refund = by_dom.get("refund")
    
    findings = analyze(
        case,
        order["data"],
        items["data"],
        payment["data"],
        shipment["data"],
        None if refund is None else refund["data"],
    )
    
    output = decide(case, findings, policy["data"], ev)
    
    # Verify contracts
    contracts.validate_output(output, f"outputs/{case_id}.json")
    verify_output(output, case_id, ev, contracts)
    
    issues[output["assessment"]["primary_issue"]] = issues.get(output["assessment"]["primary_issue"], 0) + 1

print("\nDistribution across all 100 cases:")
for k, v in sorted(issues.items()):
    print(f"  {k:24s}: {v}")

assert len(issues) == 10
assert all(v == 10 for v in issues.values())
print("\nAll 100 outputs pass schema validation and internal verification with exact 10/10 distribution!")
