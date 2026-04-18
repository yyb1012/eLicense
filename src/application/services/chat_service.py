# Time: 2026-04-18 19:38
# Description: 编排聊天业务流程并映射图输出，同时注入运行期开关以控制写回行为。
# Author: Feixue

from __future__ import annotations

from dataclasses import dataclass

from src.agent.graph.builder import Orchestrator
from src.agent.graph.state import GraphState
from src.shared.config import get_settings


@dataclass(frozen=True)
class ChatResult:
    """聊天用例层统一返回模型。"""

    answer: str
    decision: dict[str, str]
    risk_level: str
    next_action: str
    trace_id: str


class ChatService:
    """聊天应用服务：负责状态组装、编排调用和结果映射。"""

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        *,
        feature_enable_writeback: bool | None = None,
    ) -> None:
        self._orchestrator = orchestrator or Orchestrator()
        if feature_enable_writeback is None:
            feature_enable_writeback = get_settings().feature_enable_writeback
        self._feature_enable_writeback = bool(feature_enable_writeback)

    async def chat(
        self,
        *,
        session_id: str,
        work_order_id: str,
        message: str,
        user_id: str,
        trace_id: str,
    ) -> ChatResult:
        """执行一次聊天请求并返回接口可直接使用的结果。"""
        # 将接口参数映射为图状态输入。
        state: GraphState = {
            "trace_id": trace_id,
            "session_id": session_id,
            "work_order_id": work_order_id,
            "user_input": message,
            "feature_enable_writeback": self._feature_enable_writeback,
        }
        output = await self._orchestrator.run(state)

        route = output.get("route", "human_review")
        risk_level = output.get("risk_report", {}).get("risk_level", "unknown")
        next_action = _map_next_action(
            route=route,
            fallback=output.get("policy_report", {}).get("next_action", f"stub_for_{user_id}"),
        )

        # 将图输出统一映射为 ChatResult，隔离上层对图字段的依赖。
        return ChatResult(
            answer=output.get("answer_text", "[stub] request accepted"),
            decision={"route": route},
            risk_level=risk_level,
            next_action=next_action,
            trace_id=trace_id,
        )


def _map_next_action(*, route: str, fallback: str) -> str:
    """按最终路由生成稳定的下一步动作。"""
    route_to_action = {
        "pass": "proceed_to_writeback",
        "degrade": "proceed_with_degrade_mode",
        "reject": "close_as_rejected",
        "human_review": "escalate_to_human_review",
    }
    return route_to_action.get(route, fallback)
