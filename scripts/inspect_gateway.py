"""Inspect the authenticated public tool catalog; never prints credentials."""

import asyncio
import json
import sys
from pathlib import Path

from student_agent.config import Settings
from student_agent.contracts import Contracts
from student_agent.mcp_gateway import connect_gateway


async def main():
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    contracts = Contracts(root / "contracts" / "schemas")
    failures = 0
    async with connect_gateway(settings.mcp_endpoint, settings.team_api_key, contracts) as gateway:
        await gateway.list_tools()
        print("Discovered:", ", ".join(sorted(gateway.tools)))
        if "--check" in sys.argv:
            case = json.loads((root / "inputs/L3A_CASE_001.json").read_text(encoding="utf-8"))
            for name, arguments in [
                ("get_policy", {"policy_version": case["policy_version"]}),
                ("get_order", {"order_id": case["customer_request"]["claimed_order_id"]}),
            ]:
                try:
                    result = await gateway.call(name, case_id=case["case_id"], **arguments)
                    print(json.dumps(result, ensure_ascii=True, indent=2))
                except (RuntimeError, ValueError) as exc:
                    failures += 1
                    print(str(exc))
        else:
            print(json.dumps(gateway.tools, ensure_ascii=True, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
