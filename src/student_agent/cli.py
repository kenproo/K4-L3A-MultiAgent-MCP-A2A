from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx2

from .cases import load_case_set
from .competition import prepare_run
from .config import Settings
from .contracts import Contracts
from .mcp_gateway import connect_gateway
from .submission import package_submission, validate_artifacts
from .trace import TraceWriter
from .workflow import solve_case


def _root(value: str) -> Path:
    return Path(value).resolve()


async def _show_tools(root: Path) -> None:
    settings = Settings.load(root)
    contracts = Contracts(root / "contracts" / "schemas")
    async with connect_gateway(settings.mcp_endpoint, settings.team_api_key, contracts) as gateway:
        for tool in await gateway.list_tools():
            print(tool)


async def _run(root: Path) -> None:
    settings = Settings.load(root)
    case_set = load_case_set(root)
    await prepare_run(settings, case_set.version)
    contracts = Contracts(root / "contracts" / "schemas")
    staging = root / ".local" / "runs" / uuid4().hex
    output_root = staging / "outputs"
    trace_path = staging / "traces" / "trace.jsonl"
    output_root.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace = TraceWriter(trace_path, contracts)

    remaining_cases = list(case_set.case_ids)
    attempts: dict[str, int] = {}

    while remaining_cases:
        try:
            async with connect_gateway(
                settings.mcp_endpoint, settings.team_api_key, contracts
            ) as gateway:
                discovered_tools = await gateway.list_tools()
                if not discovered_tools:
                    raise RuntimeError("MCP Gateway returned no tools")
                while remaining_cases:
                    case_id = remaining_cases[0]
                    target = output_root / f"{case_id}.json"
                    initial_trace_size = trace_path.stat().st_size if trace_path.exists() else 0
                    try:
                        case = case_set.cases[case_id]
                        trace.emit(case_id=case_id, event_type="case_received", actor="coordinator")
                        output = await solve_case(case, gateway, trace)
                        contracts.validate_output(output, f"outputs/{case_id}.json")
                        if output.get("case_id") != case_id:
                            raise ValueError(f"solver returned a mismatched case_id for {case_id}")
                        temporary = target.with_suffix(".json.tmp")
                        temporary.write_text(
                            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        temporary.replace(target)
                        trace.emit(
                            case_id=case_id, event_type="case_finalized", actor="coordinator"
                        )
                        print(f"OK: {case_id}", flush=True)
                        remaining_cases.pop(0)
                        attempts[case_id] = 0
                    except Exception as exc:
                        if trace_path.exists():
                            with trace_path.open("r+", encoding="utf-8") as handle:
                                handle.truncate(initial_trace_size)
                        if target.exists():
                            target.unlink()
                        attempts[case_id] = attempts.get(case_id, 0) + 1
                        if attempts[case_id] >= 3:
                            raise
                        print(
                            f"Retrying {case_id} (attempt {attempts[case_id]}): {exc}", flush=True
                        )
                        break
        except (
            ExceptionGroup,
            BaseExceptionGroup,
            httpx2.HTTPError,
            ConnectionError,
            TimeoutError,
            OSError,
        ):
            if not remaining_cases or attempts.get(remaining_cases[0], 0) >= 3:
                raise
            await asyncio.sleep(1)

    validate_artifacts(staging, case_set, contracts)
    final_outputs = root / "outputs"
    final_outputs.mkdir(parents=True, exist_ok=True)
    for case_id in case_set.case_ids:
        (output_root / f"{case_id}.json").replace(final_outputs / f"{case_id}.json")
    for stale in final_outputs.glob("*.json"):
        if stale.stem not in case_set.case_ids:
            stale.unlink()
    (root / "traces").mkdir(parents=True, exist_ok=True)
    trace_path.replace(root / "traces" / "trace.jsonl")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Day09 L3A student workflow")
    result.add_argument("--root", default=".", help="repository root (default: current directory)")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-inputs", help="validate case-set.json and all 100 inputs")
    commands.add_parser("mcp-tools", help="authenticate and list discovered MCP tools")
    commands.add_parser("prepare-run", help="initialize the active L3A team run before MCP calls")
    commands.add_parser("run", help="run the implemented workflow for all cases")
    commands.add_parser("validate", help="validate outputs and observable trace")
    package = commands.add_parser("package", help="validate and build the submission ZIP")
    package.add_argument("--output", default="dist/submission.zip")
    return result


def main() -> None:
    args = parser().parse_args()
    root = _root(args.root)
    try:
        if args.command == "validate-inputs":
            case_set = load_case_set(root)
            print(
                f"OK: {case_set.variant_id} / {case_set.version} / "
                f"{len(case_set.case_ids)} cases"
            )
        elif args.command == "mcp-tools":
            asyncio.run(_show_tools(root))
        elif args.command == "prepare-run":
            case_set = load_case_set(root)
            metadata = asyncio.run(prepare_run(Settings.load(root), case_set.version))
            print(f"OK: active L3A run / expires {metadata['expires_at']}")
        elif args.command == "run":
            asyncio.run(_run(root))
        elif args.command == "validate":
            case_set = load_case_set(root)
            contracts = Contracts(root / "contracts" / "schemas")
            _, trace = validate_artifacts(root, case_set, contracts)
            print(f"OK: {len(case_set.case_ids)} outputs / {len(trace)} trace events")
        elif args.command == "package":
            destination = package_submission(root, root / args.output)
            print(f"OK: {destination}")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
