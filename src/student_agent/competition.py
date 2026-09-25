"""Initialize the team-scoped run required by the MCP evidence service."""

from __future__ import annotations

from typing import Any

import httpx2

from . import VARIANT_ID
from .config import Settings


async def prepare_run(settings: Settings, case_set_version: str) -> dict[str, Any]:
    # Do not follow redirects with credentials. The short public URL redirects to HTTP.
    async with httpx2.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.get(f"{settings.competition_api_url}/api/v2/competitions")
        if response.is_redirect:
            raise RuntimeError("COMPETITION_API_URL must be the direct HTTPS Workspace origin")
        response.raise_for_status()
        competition = next(
            (item for item in response.json() if item["variant_id"] == VARIANT_ID), None
        )
        if competition is None or competition["status"] != "open":
            raise RuntimeError("L3A competition is not open")
        if competition["case_set_version"] != case_set_version:
            raise ValueError("Local case-set version differs from the active competition")
        response = await client.post(
            f"{settings.competition_api_url}/api/v2/runs",
            headers={"Authorization": f"Bearer {settings.team_api_key}"},
            json={"variant_id": VARIANT_ID},
        )
        if response.status_code in (401, 403):
            raise RuntimeError("Team API key is not authorized to initialize an L3A run")
        response.raise_for_status()
        metadata = response.json()
        if metadata.get("variant_id") != VARIANT_ID:
            raise ValueError("Server initialized a different competition variant")
        if metadata.get("case_set_version") != case_set_version:
            raise ValueError("Server run does not match the local case-set")
        if metadata.get("mcp_endpoint") != settings.mcp_endpoint:
            raise ValueError("MCP_ENDPOINT does not match the endpoint returned by the run API")
        return metadata
