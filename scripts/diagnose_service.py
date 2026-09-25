"""Read public service metadata without sending credentials or following redirects."""

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx2

from student_agent.config import Settings


async def main():
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    parts = urlsplit(settings.mcp_endpoint)
    origin = f"{parts.scheme}://{parts.netloc}"
    destinations = [settings.competition_api_url, origin + "/register", origin + "/openapi.json"]
    local = root / ".local" / "diagnostics"
    local.mkdir(parents=True, exist_ok=True)
    async with httpx2.AsyncClient(timeout=20, follow_redirects=False) as client:
        if "--activate" in sys.argv:
            result = await client.post(
                origin + "/api/v2/runs",
                headers={"Authorization": f"Bearer {settings.team_api_key}"},
                json={"variant_id": "l3a"},
            )
            print("Initialize L3A run:", result.status_code)
            payload = result.json()
            result.raise_for_status()
            (local / "run.json").write_text(json.dumps(payload), encoding="utf-8")
            print("Response fields:", sorted(payload))
            print(
                json.dumps(
                    {
                        key: value
                        for key, value in payload.items()
                        if key in {"variant_id", "case_set_version", "status", "mcp_endpoint"}
                    }
                )
            )
            return
        if "--auth" in sys.argv:
            for path in ["/api/health", "/api/v2/competitions", "/api/v2/me/submissions"]:
                headers = (
                    {"Authorization": f"Bearer {settings.team_api_key}"} if "/me/" in path else {}
                )
                result = await client.get(origin + path, headers=headers)
                print(path, result.status_code, flush=True)
                payload = result.json()
                if "/me/" in path and result.is_success:
                    print("Team authentication succeeded; submission history not displayed.")
                else:
                    print(json.dumps(payload, ensure_ascii=True))
            return
        for index, url in enumerate(destinations):
            try:
                result = await client.get(url)
                print(
                    json.dumps(
                        {
                            "url": url,
                            "status": result.status_code,
                            "location": result.headers.get("location"),
                            "content_type": result.headers.get("content-type"),
                        }
                    ),
                    flush=True,
                )
                if result.status_code == 200:
                    (local / f"public-{index}.txt").write_text(result.text, encoding="utf-8")
            except httpx2.HTTPError as exc:
                print(type(exc).__name__, url, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
