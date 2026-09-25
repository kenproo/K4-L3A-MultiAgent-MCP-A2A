import asyncio
from pathlib import Path

import httpx2
import pytest

from student_agent import competition
from student_agent.config import Settings


@pytest.mark.parametrize(
    "status,version,posts", [("open", "v1", 1), ("closed", "v1", 0), ("open", "wrong", 0)]
)
def test_prepare_run_checks_state_before_initializing(monkeypatch, status, version, posts):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            return httpx2.Response(
                200, json=[{"variant_id": "l3a", "status": status, "case_set_version": version}]
            )
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        assert request.url.path == "/api/v2/runs"
        return httpx2.Response(
            201,
            json={
                "variant_id": "l3a",
                "case_set_version": "v1",
                "mcp_endpoint": "https://example.invalid/mcp",
            },
        )

    original = httpx2.AsyncClient
    monkeypatch.setattr(
        competition.httpx2,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx2.MockTransport(handler), **kwargs),
    )
    settings = Settings(
        "https://example.invalid", "synthetic-test-key", "https://example.invalid/mcp", Path.cwd()
    )
    if posts:
        assert asyncio.run(competition.prepare_run(settings, "v1"))["variant_id"] == "l3a"
    else:
        with pytest.raises((RuntimeError, ValueError)):
            asyncio.run(competition.prepare_run(settings, "v1"))
    assert len([call for call in calls if call.method == "POST"]) == posts
