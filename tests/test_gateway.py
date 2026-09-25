from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from student_agent.agents import CaseContext, Specialist
from student_agent.contracts import Contracts
from student_agent.mcp_gateway import EvidenceGateway
from student_agent.trace import TraceWriter


def contracts():
    return Contracts(Path(__file__).resolve().parents[1] / "contracts" / "schemas")


class Tool:
    name = "get_order"

    def model_dump(self, **kwargs):
        return {"name": self.name, "inputSchema": {"type": "object"}}


class Session:
    def __init__(self, failed=False):
        self.failed = failed
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=[Tool()])

    async def call_tool(self, tool, arguments):
        self.calls.append((tool, arguments))
        return SimpleNamespace(
            is_error=self.failed,
            content=[SimpleNamespace(text="Service unavailable")],
            structured_content={
                "schema_version": "day09-mcp-evidence-v1",
                "evidence_ref": "ev_" + "x" * 24,
                "result_hash": "sha256:" + "0" * 64,
                "domain": "order",
                "data": {"order_id": arguments["order_id"]},
            },
        )


def test_sdk_v2_response_and_case_scope():
    session = Session()
    result = asyncio.run(
        EvidenceGateway(session, contracts()).call(
            "get_order", case_id="CASE_001", order_id="order-1"
        )
    )
    assert result["data"]["order_id"] == "order-1"
    assert session.calls == [("get_order", {"case_id": "CASE_001", "order_id": "order-1"})]


def test_sdk_error_does_not_become_evidence():
    gateway = EvidenceGateway(Session(failed=True), contracts())
    with pytest.raises(RuntimeError, match="Service unavailable"):
        asyncio.run(gateway.call("get_order", case_id="CASE_001", order_id="order-1"))


def test_undiscovered_tool_is_not_called():
    session = Session()
    with pytest.raises(ValueError, match="not discovered"):
        asyncio.run(EvidenceGateway(session, contracts()).call("guessed", case_id="CASE_001"))
    assert session.calls == []


def test_case_cache_does_not_cross_case_boundaries(tmp_path):
    session = Session()
    gateway = EvidenceGateway(session, contracts())
    trace = TraceWriter(tmp_path / "trace.jsonl", contracts())
    specialist = Specialist("order-agent", frozenset({"get_order"}))

    async def exercise():
        for case_id in ["CASE_001", "CASE_002"]:
            context = CaseContext(case_id, gateway, trace)
            await specialist.collect(context, "get_order", order_id="order-1")
            await specialist.collect(context, "get_order", order_id="order-1")
            assert len(context.evidence) == 1

    asyncio.run(exercise())
    assert len(session.calls) == 2
    assert [args["case_id"] for _, args in session.calls] == ["CASE_001", "CASE_002"]


def test_specialist_rejects_unauthorized_tool(tmp_path):
    context = CaseContext(
        "CASE_001",
        EvidenceGateway(Session(), contracts()),
        TraceWriter(tmp_path / "trace.jsonl", contracts()),
    )
    with pytest.raises(ValueError, match="not authorized"):
        asyncio.run(Specialist("payment-agent", frozenset()).collect(context, "get_order"))
