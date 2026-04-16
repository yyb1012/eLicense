from __future__ import annotations

from dataclasses import dataclass

from src.agent.graph.builder import Orchestrator
from src.agent.graph.state import GraphState


@dataclass(frozen=True)
class ChatResult:
    answer: str
    decision: dict[str, str]
    risk_level: str
    next_action: str
    trace_id: str


class ChatService:
    """Minimal chat service for N02/N03."""

    def __init__(self, orchestrator: Orchestrator | None = None) -> None:
        self._orchestrator = orchestrator or Orchestrator()

    async def chat(
        self,
        *,
        session_id: str,
        work_order_id: str,
        message: str,
        user_id: str,
        trace_id: str,
    ) -> ChatResult:
        state: GraphState = {
            "trace_id": trace_id,
            "session_id": session_id,
            "work_order_id": work_order_id,
            "user_input": message,
        }
        output = await self._orchestrator.run(state)
        return ChatResult(
            answer=output.get("answer_text", "[stub] request accepted"),
            decision={"route": output.get("route", "degrade")},
            risk_level="unknown",
            next_action=f"stub_for_{user_id}",
            trace_id=trace_id,
        )
