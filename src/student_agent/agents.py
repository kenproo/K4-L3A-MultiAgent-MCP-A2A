"""Case-scoped specialist handoffs and evidence acquisition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter


@dataclass
class CaseContext:
    case_id: str
    gateway: EvidenceGateway
    trace: TraceWriter
    evidence: list[dict[str, Any]] = field(default_factory=list)
    cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = field(
        default_factory=dict
    )

    def emit(self, event_type: str, actor: str, **kwargs: Any) -> None:
        self.trace.emit(case_id=self.case_id, event_type=event_type, actor=actor, **kwargs)

    async def acquire(self, actor: str, tool: str, **arguments: str) -> dict[str, Any]:
        key = (tool, tuple(sorted(arguments.items())))
        if key not in self.cache:
            for attempt in range(3):
                try:
                    result = await asyncio.wait_for(
                        self.gateway.call(tool, case_id=self.case_id, **arguments), timeout=90
                    )
                    break
                except (TimeoutError, ConnectionError):
                    self.emit(
                        "handoff",
                        actor,
                        target="coordinator",
                        decision_code="MCP_TIMEOUT",
                        attributes={"attempt": attempt + 1},
                    )
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2**attempt)
            self.cache[key] = result
            self.evidence.append(result)
        result = self.cache[key]
        self.emit(
            "tool_result_consumed", actor, tool_name=tool, evidence_refs=[result["evidence_ref"]]
        )
        return result


@dataclass(frozen=True)
class Specialist:
    actor: str
    allowed_tools: frozenset[str]

    async def collect(self, context: CaseContext, tool: str, **arguments: str) -> dict[str, Any]:
        if tool not in self.allowed_tools:
            raise ValueError(f"{self.actor} is not authorized to call {tool}")
        context.emit(
            "task_assigned",
            "coordinator",
            target=self.actor,
            decision_code="COLLECT_EVIDENCE",
            attributes={"tool": tool},
        )
        result = await context.acquire(self.actor, tool, **arguments)
        context.emit(
            "handoff",
            self.actor,
            target="coordinator",
            decision_code="EVIDENCE_READY",
            evidence_refs=[result["evidence_ref"]],
        )
        return result
