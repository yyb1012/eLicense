# Time: 2026-04-18 22:05
# Description: 负责统一执行质量门禁并产出最终路由，收敛 N05~N08 的降级与人工介入信号。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.agent.graph.state import GraphState
from src.shared.logger import get_logger

logger = get_logger(__name__)


async def run_quality_gate_subgraph(state: GraphState) -> GraphState:
    """执行 N09：Quality Gate 并生成最终 route。"""
    decision_final = state.get("decision_final", {})
    risk_report = state.get("risk_report", {})
    errors = [str(item) for item in state.get("errors", [])]
    self_critic_report = state.get("self_critic_report", {})
    loop_status = state.get("analysis_loop_status", {})

    route, route_reason, blocking_signals = _decide_route(
        decision_final=decision_final,
        risk_report=risk_report,
        errors=errors,
        self_critic_report=self_critic_report,
        loop_status=loop_status,
    )

    quality_report = {
        "version": "n09-quality-gate-v1",
        "checks": {
            "gate_1_contract": _gate_1_contract(decision_final=decision_final, risk_report=risk_report),
            "gate_2_flow": _gate_2_flow(decision_final=decision_final, blocking_signals=blocking_signals),
            "gate_3_release": _gate_3_release(
                route=route,
                self_critic_report=self_critic_report,
                blocking_signals=blocking_signals,
            ),
        },
        "blocking_signals": blocking_signals,
        "route_reason": route_reason,
    }

    logger.info(
        "quality_gate_summary",
        extra={
            "extra_fields": {
                "route": route,
                "route_reason": route_reason,
                "blocking_signals": blocking_signals,
            }
        },
    )

    return {
        "quality_report": quality_report,
        "route": route,
    }


def _decide_route(
    *,
    decision_final: dict[str, Any],
    risk_report: dict[str, Any],
    errors: list[str],
    self_critic_report: dict[str, Any],
    loop_status: dict[str, Any],
) -> tuple[str, str, list[str]]:
    """集中决策路由规则，保证同一输入下路由稳定可复现。"""
    blocking_signals = sorted(
        {
            signal
            for signal in errors
            if signal
            in {
                "analysis_retry_budget_exhausted",
                "evidence_retrieval_requires_human_review",
                "orchestrator_retry_loop_guard_triggered",
            }
        }
    )

    action = str(decision_final.get("action", "human_review"))
    risk_level = str(risk_report.get("risk_level", "unknown"))
    self_critic_passed = bool(self_critic_report.get("passed", True))
    loop_exhausted = bool(loop_status.get("needs_more_evidence", False)) and not bool(
        loop_status.get("can_retry", True)
    )

    if action == "reject":
        return "reject", "decision_final_reject", blocking_signals
    if risk_level == "critical":
        return "reject", "critical_risk_level", blocking_signals
    if blocking_signals:
        return "human_review", "blocking_signal_detected", blocking_signals
    if action == "human_review" or loop_exhausted:
        return "human_review", "decision_requires_human_review", blocking_signals
    if not self_critic_passed:
        return "human_review", "self_critic_not_passed", blocking_signals
    if action == "degrade" or risk_level == "high":
        return "degrade", "high_risk_or_degrade_action", blocking_signals
    if action == "pass":
        return "pass", "quality_gate_passed", blocking_signals
    return "human_review", "fallback_human_review", blocking_signals


def _gate_1_contract(*, decision_final: dict[str, Any], risk_report: dict[str, Any]) -> bool:
    """Gate-1：接口契约稳定性检查。"""
    return bool(decision_final.get("action")) and bool(risk_report.get("risk_level"))


def _gate_2_flow(*, decision_final: dict[str, Any], blocking_signals: list[str]) -> bool:
    """Gate-2：主流程与降级路径检查。"""
    return bool(decision_final.get("version")) and not (
        decision_final.get("action") == "pass" and blocking_signals
    )


def _gate_3_release(
    *,
    route: str,
    self_critic_report: dict[str, Any],
    blocking_signals: list[str],
) -> bool:
    """Gate-3：发布前风险约束检查。"""
    if route == "pass":
        return bool(self_critic_report.get("passed", False)) and not blocking_signals
    return True
