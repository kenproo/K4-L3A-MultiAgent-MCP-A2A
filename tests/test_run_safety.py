import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from student_agent import cli
from student_agent.contracts import Contracts


def test_failed_run_preserves_published_artifacts(tmp_path, monkeypatch):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "traces").mkdir()
    output_path = tmp_path / "outputs" / "CASE_001.json"
    trace_path = tmp_path / "traces" / "trace.jsonl"
    output_path.write_text("previous output", encoding="utf-8")
    trace_path.write_text("previous trace", encoding="utf-8")
    contracts = Contracts(Path(__file__).resolve().parents[1] / "contracts" / "schemas")
    monkeypatch.setattr(cli, "Contracts", lambda path: contracts)
    monkeypatch.setattr(
        cli.Settings,
        "load",
        lambda root: SimpleNamespace(
            mcp_endpoint="https://example.invalid/mcp", team_api_key="test-only"
        ),
    )
    monkeypatch.setattr(
        cli,
        "load_case_set",
        lambda root: SimpleNamespace(
            case_ids=("CASE_001",), cases={"CASE_001": {"case_id": "CASE_001"}}, version="test-v1"
        ),
    )

    class Gateway:
        async def list_tools(self):
            return ["get_order"]

    @asynccontextmanager
    async def connect(*args):
        yield Gateway()

    async def fail(*args):
        raise RuntimeError("MCP unavailable")

    async def prepare(*args):
        return {}

    monkeypatch.setattr(cli, "connect_gateway", connect)
    monkeypatch.setattr(cli, "solve_case", fail)
    monkeypatch.setattr(cli, "prepare_run", prepare)
    with pytest.raises(RuntimeError, match="MCP unavailable"):
        asyncio.run(cli._run(tmp_path))
    assert output_path.read_text(encoding="utf-8") == "previous output"
    assert trace_path.read_text(encoding="utf-8") == "previous trace"
