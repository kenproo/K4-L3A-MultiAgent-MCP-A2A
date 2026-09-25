"""Dependency-free MCP catalog diagnostic (does not print credentials)."""

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    config = {}
    for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip().strip("\"'")
    if "--status" in sys.argv:

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        for url in [config["COMPETITION_API_URL"], config["MCP_ENDPOINT"].removesuffix("/mcp")]:
            try:
                with opener.open(url, timeout=15) as response:
                    print(url, response.status, response.headers.get("location"))
            except urllib.error.HTTPError as exc:
                print(url, exc.code, exc.headers.get("location"))
            except urllib.error.URLError as exc:
                print(url, str(exc.reason))
        return
    headers = {
        "Authorization": "Bearer " + config["COMPETITION_TEAM_API_KEY"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def request(payload):
        req = urllib.request.Request(
            config["MCP_ENDPOINT"], data=json.dumps(payload).encode(), headers=headers
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                headers["Mcp-Session-Id"] = session
            body = response.read().decode()
            if body.startswith("event:") or body.startswith("data:"):
                return json.loads(
                    next(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
                )
            return json.loads(body) if body else {}

    initialized = request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "day09-catalog-probe", "version": "0.1.0"},
            },
        }
    )
    headers["MCP-Protocol-Version"] = initialized.get("result", {}).get(
        "protocolVersion", "2025-03-26"
    )
    request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    catalog = request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    if "--sample" not in sys.argv:
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
        return
    discovered = {tool["name"] for tool in catalog["result"]["tools"]}
    destination = root / ".local" / "samples"
    destination.mkdir(parents=True, exist_ok=True)

    def collect(index):
        case = json.loads(
            (root / "inputs" / f"L3A_CASE_{index:03d}.json").read_text(encoding="utf-8")
        )
        results = {}
        names = [
            "get_order",
            "get_order_items",
            "get_order_payments",
            "get_shipment_summary",
            "get_payment_timeline",
            "get_refund_timeline",
            "get_policy",
            "get_sellers",
        ]
        for number, name in enumerate(names):
            assert name in discovered
            args = {"case_id": case["case_id"]}
            args.update(
                {"policy_version": case["policy_version"]}
                if name == "get_policy"
                else {"order_id": case["customer_request"]["claimed_order_id"]}
            )
            response = request(
                {
                    "jsonrpc": "2.0",
                    "id": index * 100 + number,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": args},
                }
            )
            results[name] = response
        (destination / f"{case['case_id']}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(case["case_id"], "sample collected", flush=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(collect, range(1, 11)))


if __name__ == "__main__":
    main()
