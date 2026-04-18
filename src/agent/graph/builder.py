# Time: 2026-04-18 19:57
# Description: 构建并执行主编排图，串联 N05~N11 并为 N13 提供故障注入与回放稳定性支持。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.agent.graph.state import GraphState
from src.agent.graph.subgraphs.analysis_subgraph import run_analysis_subgraph
from src.agent.graph.subgraphs.audit_subgraph import run_audit_subgraph
from src.agent.graph.subgraphs.decision_subgraph import run_decision_subgraph
from src.agent.graph.subgraphs.evidence_subgraph import run_evidence_subgraph
from src.agent.graph.subgraphs.planner_subgraph import run_planner_subgraph
from src.agent.graph.subgraphs.quality_gate_subgraph import run_quality_gate_subgraph
from src.agent.graph.subgraphs.writeback_subgraph import run_writeback_subgraph
from src.shared.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_ANALYSIS_ATTEMPTS = 2

try:
    # LangGraph 可用时走真实图执行路径。
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - fallback for dependency bootstrap stage
    # 依赖未安装时启用本地降级路径，保证接口可持续联调。
    END = "END"
    START = "START"
    StateGraph = None


def _merge_patch(base: GraphState, patch: GraphState) -> GraphState:
    """在 fallback 路径中统一执行状态合并，保持与 LangGraph merge 语义一致。"""
    return {**base, **patch}


def _context_bootstrap(state: GraphState) -> GraphState:
    """补齐基础状态字段，避免后续节点重复判空。"""
    history = state.get("evidence_query_history", [])
    if not isinstance(history, list):
        history = []
    fault_injection = state.get("fault_injection", {})
    if not isinstance(fault_injection, dict):
        fault_injection = {}

    return {
        "errors": list(state.get("errors", [])),
        "analysis_attempt_count": _as_int(state.get("analysis_attempt_count", 0), default=0),
        "max_analysis_attempts": _safe_max_attempts(
            state.get("max_analysis_attempts", DEFAULT_MAX_ANALYSIS_ATTEMPTS)
        ),
        "evidence_query_history": history,
        "fault_injection": {
            "simulate_fail_fts": bool(fault_injection.get("simulate_fail_fts", False)),
            "simulate_fail_vector": bool(fault_injection.get("simulate_fail_vector", False)),
            "writeback_fail": bool(fault_injection.get("writeback_fail", False)),
        },
    }


async def _planner_subgraph_entry(state: GraphState) -> GraphState:
    """N05 Planner 子图入口：写入 intent 与 plan 草案。"""
    return await run_planner_subgraph(state)


async def _evidence_subgraph_entry(state: GraphState) -> GraphState:
    """N06 Evidence 子图入口：写入检索命中与 evidence_bundle。"""
    return await run_evidence_subgraph(state)


async def _analysis_subgraph_entry(state: GraphState) -> GraphState:
    """N07 Analysis 子图入口：写入 policy_report、risk_report 与回路状态。"""
    return await run_analysis_subgraph(state)


async def _decision_subgraph_entry(state: GraphState) -> GraphState:
    """N08 Decision 子图入口：写入 decision_draft、self_critic_report 与 decision_final。"""
    return await run_decision_subgraph(state)


async def _quality_gate_subgraph_entry(state: GraphState) -> GraphState:
    """N09 QualityGate 子图入口：写入 quality_report 与最终 route。"""
    return await run_quality_gate_subgraph(state)


async def _writeback_subgraph_entry(state: GraphState) -> GraphState:
    """N10 WriteBack 子图入口：在 pass 路由下输出写回结果与补偿信号。"""
    return await run_writeback_subgraph(state)


async def _audit_subgraph_entry(state: GraphState) -> GraphState:
    """N11 Audit 子图入口：聚合关键状态并输出审计快照。"""
    return await run_audit_subgraph(state)


def _analysis_route_selector(state: GraphState) -> str:
    """根据分析结果决定是否回到 Evidence 继续补证据。"""
    return "retry_evidence" if _should_retry_after_analysis(state) else "to_decision"


def _post_quality_gate_route_selector(state: GraphState) -> str:
    """根据质量门禁路由决定是否执行写回。"""
    return "to_writeback" if _should_enter_writeback(state) else "to_audit"


def _should_retry_after_analysis(state: GraphState) -> bool:
    """统一回路判定逻辑，保证图执行与 fallback 执行行为一致。"""
    loop_status = state.get("analysis_loop_status", {})
    if isinstance(loop_status, dict) and "can_retry" in loop_status:
        return bool(loop_status.get("can_retry", False))

    policy_report = state.get("policy_report", {})
    if not isinstance(policy_report, dict):
        return False
    if policy_report.get("next_action") != "collect_more_evidence":
        return False

    attempt = _as_int(state.get("analysis_attempt_count", 0), default=0)
    max_attempts = _safe_max_attempts(
        state.get("max_analysis_attempts", DEFAULT_MAX_ANALYSIS_ATTEMPTS)
    )
    return attempt < max_attempts


def _should_enter_writeback(state: GraphState) -> bool:
    """仅当质量门禁放行 pass 时进入写回节点。"""
    return str(state.get("route", "human_review")) == "pass"


def _compose_output(state: GraphState) -> GraphState:
    """输出节点：聚合 N05~N11 结果并生成接口层可直接使用的回答文本。"""
    message = state.get("user_input", "").strip() or "empty message"
    intent = state.get("intent", "general_consultation")
    route = state.get("route", "human_review")
    risk_level = state.get("risk_report", {}).get("risk_level", "unknown")
    action = state.get("decision_final", {}).get("action", "human_review")
    writeback_status = state.get("writeback_result", {}).get("status", "not_executed")
    attempts = _as_int(state.get("analysis_attempt_count", 0), default=0)
    evidence_count = len(state.get("evidence_bundle", []))

    return {
        "answer_text": (
            f"[stub] request accepted: {message} "
            f"(intent={intent}, route={route}, action={action}, "
            f"risk={risk_level}, evidence={evidence_count}, "
            f"analysis_attempts={attempts}, writeback={writeback_status})"
        ),
    }


class Orchestrator:
    """N11 阶段最小可执行编排器，包含补证据回路、写回与审计闭环。"""

    def __init__(self) -> None:
        self._compiled_graph = self._build_graph()

    def _build_graph(self):
        # 图依赖缺失时返回 None，run() 内会走本地顺序执行。
        if StateGraph is None:
            logger.warning("langgraph_not_installed_fallback_enabled")
            return None

        graph = StateGraph(GraphState)
        graph.add_node("context_bootstrap", _context_bootstrap)
        graph.add_node("planner_subgraph", _planner_subgraph_entry)
        graph.add_node("evidence_subgraph", _evidence_subgraph_entry)
        graph.add_node("analysis_subgraph", _analysis_subgraph_entry)
        graph.add_node("decision_subgraph", _decision_subgraph_entry)
        graph.add_node("quality_gate_subgraph", _quality_gate_subgraph_entry)
        graph.add_node("writeback_subgraph", _writeback_subgraph_entry)
        graph.add_node("audit_subgraph", _audit_subgraph_entry)
        graph.add_node("compose_output", _compose_output)

        graph.add_edge(START, "context_bootstrap")
        graph.add_edge("context_bootstrap", "planner_subgraph")
        graph.add_edge("planner_subgraph", "evidence_subgraph")
        graph.add_edge("evidence_subgraph", "analysis_subgraph")
        graph.add_conditional_edges(
            "analysis_subgraph",
            _analysis_route_selector,
            {
                "retry_evidence": "evidence_subgraph",
                "to_decision": "decision_subgraph",
            },
        )
        graph.add_edge("decision_subgraph", "quality_gate_subgraph")
        graph.add_conditional_edges(
            "quality_gate_subgraph",
            _post_quality_gate_route_selector,
            {
                "to_writeback": "writeback_subgraph",
                "to_audit": "audit_subgraph",
            },
        )
        graph.add_edge("writeback_subgraph", "audit_subgraph")
        graph.add_edge("audit_subgraph", "compose_output")
        graph.add_edge("compose_output", END)
        return graph.compile()

    async def run(self, state: GraphState) -> GraphState:
        # 保持与图结构等价的执行顺序，便于依赖恢复后平滑切回图模式。
        if self._compiled_graph is None:
            local_state = dict(state)
            local_state = _merge_patch(local_state, _context_bootstrap(local_state))
            local_state = _merge_patch(local_state, await _planner_subgraph_entry(local_state))
            local_state = _merge_patch(local_state, await _evidence_subgraph_entry(local_state))
            local_state = _merge_patch(local_state, await _analysis_subgraph_entry(local_state))

            loop_guard = 0
            # 回路受 analysis_attempt_count/max_analysis_attempts 双重约束，避免死循环。
            while _should_retry_after_analysis(local_state):
                loop_guard += 1
                if loop_guard > 8:
                    errors = list(local_state.get("errors", []))
                    errors.append("orchestrator_retry_loop_guard_triggered")
                    local_state = _merge_patch(local_state, {"errors": errors})
                    break

                logger.info(
                    "orchestrator_retry_evidence",
                    extra={
                        "extra_fields": {
                            "analysis_attempt_count": local_state.get("analysis_attempt_count", 0),
                            "max_analysis_attempts": local_state.get("max_analysis_attempts", 0),
                        }
                    },
                )
                local_state = _merge_patch(local_state, await _evidence_subgraph_entry(local_state))
                local_state = _merge_patch(local_state, await _analysis_subgraph_entry(local_state))

            local_state = _merge_patch(local_state, await _decision_subgraph_entry(local_state))
            local_state = _merge_patch(local_state, await _quality_gate_subgraph_entry(local_state))
            if _should_enter_writeback(local_state):
                local_state = _merge_patch(local_state, await _writeback_subgraph_entry(local_state))
            local_state = _merge_patch(local_state, await _audit_subgraph_entry(local_state))
            local_state = _merge_patch(local_state, _compose_output(local_state))
            return local_state

        return await self._compiled_graph.ainvoke(state)


def _as_int(value: Any, *, default: int) -> int:
    """解析整数字段，避免脏值导致编排判定异常。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_max_attempts(value: Any) -> int:
    """最大尝试次数至少为 1，避免回路配置导致 Analysis 不可执行。"""
    return max(_as_int(value, default=DEFAULT_MAX_ANALYSIS_ATTEMPTS), 1)
