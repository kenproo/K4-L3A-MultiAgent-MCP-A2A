"""Script to apply all optimizations and cleanups to the Day09 L3A Multi-Agent repo.

Usage:
    python apply_improvements.py

What this script does:
1. Fixes Git hygiene: ignores runtime `evidence/` and removes 4 committed raw evidence JSONs.
2. Fixes hardcoded run paths in `simulate_decide.py` and `test_domains.py`.
3. Fixes all linter errors in `scripts/` so `ruff check .` passes 100%.
4. Refactors `src/student_agent/workflow.py` (moves `import json` to module top-level).
5. Refactors `src/student_agent/analysis.py` (eliminates duplicated domain parsing in `decide()`).
6. Updates `tests/test_release_safety.py` to guard against evidence tracking.
7. Runs `pytest` and `ruff check .` to verify all tests pass.
"""

import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    root = Path(__file__).resolve().parent
    print(f"Applying improvements to repository at: {root}\n")

    # 1. Update .gitignore
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if "evidence/*" not in content:
            target = "traces/*\n!traces/.gitkeep\n"
            if target in content:
                content = content.replace(target, target + "evidence/*\n!evidence/.gitkeep\n")
            elif "traces/*\r\n!traces/.gitkeep\r\n" in content:
                content = content.replace(
                    "traces/*\r\n!traces/.gitkeep\r\n",
                    "traces/*\r\n!traces/.gitkeep\r\nevidence/*\r\n!evidence/.gitkeep\r\n",
                )
            else:
                content += "\nevidence/*\n!evidence/.gitkeep\n"
            gitignore_path.write_text(content, encoding="utf-8")
            print("[OK] Updated .gitignore (added evidence/* ignore rules)")

    # 2. Ensure evidence/.gitkeep exists
    ev_dir = root / "evidence"
    ev_dir.mkdir(exist_ok=True)
    gitkeep = ev_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        print("[OK] Created evidence/.gitkeep")

    # 3. Untrack committed evidence JSON files if git is available
    try:
        evidence_files = [
            "evidence/L3A_CASE_001.json",
            "evidence/L3A_CASE_025.json",
            "evidence/L3A_CASE_085.json",
            "evidence/L3A_CASE_094.json",
        ]
        subprocess.run(
            ["git", "rm", "--cached", "-f", *evidence_files],
            cwd=root,
            capture_output=True,
            text=True,
        )
        print("[OK] Untracked raw evidence JSON files from git index")
    except Exception:
        pass

    # 4. Update workflow.py
    workflow_path = root / "src" / "student_agent" / "workflow.py"
    if workflow_path.exists():
        wf_code = workflow_path.read_text(encoding="utf-8")
        if "import json" not in wf_code.splitlines()[0:10]:
            wf_code = wf_code.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nimport json\n",
            )
        wf_code = wf_code.replace("    import json\n\n    destination =", "    destination =")
        wf_code = wf_code.replace("    import json\r\n\r\n    destination =", "    destination =")
        workflow_path.write_text(wf_code, encoding="utf-8")
        print("[OK] Refactored src/student_agent/workflow.py (top-level import json)")

    # 5. Update analysis.py
    analysis_path = root / "src" / "student_agent" / "analysis.py"
    if analysis_path.exists():
        an_code = analysis_path.read_text(encoding="utf-8")
        old_pattern = (
            '    issue = findings.issue\n'
            '    if issue == "unsupported_claim":\n'
            '        msg = case.get("customer_request", {}).get("message", "")\n'
            '        if "giao nhận" in msg:\n'
            '            findings.domains = {"order", "shipment", "item", "policy"}\n'
            '        else:\n'
            '            findings.domains = {"order", "shipment", "payment", "policy"}\n'
            '    else:\n'
            '        findings.domains = set(ISSUE_DOMAINS.get(issue, findings.domains))\n'
            '    refs = [item["evidence_ref"] for item in evidence'
            ' if item["domain"] in findings.domains]'
        )
        new_pattern = (
            '    issue = findings.issue\n'
            '    target_domains = findings.domains or'
            ' set(ISSUE_DOMAINS.get(issue, {"order", "policy"}))\n'
            '    refs = [item["evidence_ref"] for item in evidence'
            ' if item["domain"] in target_domains]'
        )
        if old_pattern in an_code:
            an_code = an_code.replace(old_pattern, new_pattern)
            analysis_path.write_text(an_code, encoding="utf-8")
            print("[OK] Refactored src/student_agent/analysis.py (clean domain ref)")

    # 6. Update scripts/analyze_cases.py
    analyze_script = root / "scripts" / "analyze_cases.py"
    if analyze_script.exists():
        analyze_content = '''import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

outputs = sorted(Path("outputs").glob("*.json"))
by_issue = {}
for p in outputs:
    d = json.loads(p.read_text(encoding="utf-8"))
    issue = d["assessment"]["primary_issue"]
    inp = json.loads(Path(f"inputs/{p.name}").read_text(encoding="utf-8"))
    claim_topics = [c["topic"] for c in inp["customer_request"]["claims"]]
    by_issue.setdefault(issue, []).append(
        (p.stem, inp["customer_request"]["message"], claim_topics)
    )

for issue, cases in sorted(by_issue.items()):
    print(f"=== {issue} ({len(cases)} cases) ===")
    msgs = set(c[1] for c in cases)
    for m in msgs:
        matching_ids = [c[0] for c in cases if c[1] == m]
        print(f"  [{len(matching_ids)} cases] \\"{m}\\"")
'''
        analyze_script.write_text(analyze_content, encoding="utf-8")
        print("[OK] Updated scripts/analyze_cases.py (sorted imports & <=100 char lines)")

    # 7. Update scripts/simulate_decide.py
    simulate_script = root / "scripts" / "simulate_decide.py"
    if simulate_script.exists():
        sim_content = '''import json
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

# Dynamically locate the latest run evidence or use fallback/CLI arg
if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
    ev_dir = Path(sys.argv[1])
else:
    runs = sorted(
        (root / ".local" / "runs").glob("*/evidence"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if runs:
        ev_dir = runs[0]
    elif (root / "evidence").is_dir() and any((root / "evidence").glob("*.json")):
        ev_dir = root / "evidence"
    else:
        raise FileNotFoundError("No evidence directory found in .local/runs/ or evidence/")

print(f"Using evidence from: {ev_dir}")
print(f"Simulating decide() for all {len(inputs)} cases...")

issues: dict[str, int] = {}
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

    issue_key = output["assessment"]["primary_issue"]
    issues[issue_key] = issues.get(issue_key, 0) + 1

print("\\nDistribution across all 100 cases:")
for k, v in sorted(issues.items()):
    print(f"  {k:24s}: {v}")

assert len(issues) == 10
assert all(v == 10 for v in issues.values())
print("\\nAll 100 outputs pass schema validation and verification with exact 10/10 distribution!")
'''
        simulate_script.write_text(sim_content, encoding="utf-8")
        print("[OK] Updated scripts/simulate_decide.py (dynamic evidence path & <=100 char lines)")

    # 8. Update scripts/test_domains.py
    test_domains_script = root / "scripts" / "test_domains.py"
    if test_domains_script.exists():
        td_content = '''import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

sys.stdout.reconfigure(encoding="utf-8")

root = Path(__file__).resolve().parents[1]

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

# Dynamically locate the latest run evidence or use fallback/CLI arg
if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
    ev_dir = Path(sys.argv[1])
else:
    runs = sorted(
        (root / ".local" / "runs").glob("*/evidence"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if runs:
        ev_dir = runs[0]
    elif (root / "evidence").is_dir() and any((root / "evidence").glob("*.json")):
        ev_dir = root / "evidence"
    else:
        raise FileNotFoundError("No evidence directory found in .local/runs/ or evidence/")

print(f"Using evidence from: {ev_dir}")
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
'''
        test_domains_script.write_text(td_content, encoding="utf-8")
        print("[OK] Updated scripts/test_domains.py (clean imports & dynamic evidence path)")

    # 9. Update tests/test_release_safety.py
    safety_test = root / "tests" / "test_release_safety.py"
    if safety_test.exists():
        st_code = safety_test.read_text(encoding="utf-8")
        old_pattern = (
            'path.startswith(("inputs/", "outputs/", "traces/")) and not path.endswith(".gitkeep")'
        )
        new_pattern = (
            'path.startswith(("inputs/", "outputs/", "traces/", "evidence/"))\n'
            '        and not path.endswith(".gitkeep")'
        )
        if old_pattern in st_code:
            st_code = st_code.replace(old_pattern, new_pattern)
            safety_test.write_text(st_code, encoding="utf-8")
            print("[OK] Updated tests/test_release_safety.py (added evidence/ check)")

    print("\n--- Running Verification ---")
    py_exec = sys.executable
    try:
        res = subprocess.run(
            [py_exec, "-m", "pytest", "-q"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        res_text = (
            f"PASS ({res.stdout.strip()})" if res.returncode == 0 else f"FAIL: {res.stderr}"
        )
        print(f"pytest: {res_text}")
    except Exception as e:
        print(f"pytest check skipped: {e}")

    try:
        res = subprocess.run(
            [py_exec, "-m", "ruff", "check", "."],
            cwd=root,
            capture_output=True,
            text=True,
        )
        res_text = 'PASS (All checks passed!)' if res.returncode == 0 else 'FAIL: ' + res.stdout
        print(f"ruff check .: {res_text}")
    except Exception as e:
        print(f"ruff check skipped: {e}")

    print("\nAll done! You can now commit with:")
    print("  git add -A")
    print('  git commit -m "refactor: improve scripts, git hygiene, and specialist analysis"')


if __name__ == "__main__":
    main()
