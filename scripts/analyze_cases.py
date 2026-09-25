import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

outputs = sorted(Path("outputs").glob("*.json"))
by_issue = {}
for p in outputs:
    d = json.loads(p.read_text(encoding="utf-8"))
    issue = d["assessment"]["primary_issue"]
    inp = json.loads(Path(f"inputs/{p.name}").read_text(encoding="utf-8"))
    by_issue.setdefault(issue, []).append((p.stem, inp["customer_request"]["message"], [c["topic"] for c in inp["customer_request"]["claims"]]))

for issue, cases in sorted(by_issue.items()):
    print(f"=== {issue} ({len(cases)} cases) ===")
    msgs = set(c[1] for c in cases)
    for m in msgs:
        matching_ids = [c[0] for c in cases if c[1] == m]
        print(f"  [{len(matching_ids)} cases] \"{m}\"")
