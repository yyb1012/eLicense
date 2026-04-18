# Time: 2026-04-18 19:56
# Description: 定义主编排图共享状态结构，并覆盖 N05~N13 阶段回放与故障注入所需字段。
# Author: Feixue

from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    """定义主图在各子图间传递的共享状态。"""

    # 请求上下文
    trace_id: str
    session_id: str
    work_order_id: str
    user_input: str

    # N05 Planner 产物
    intent: str
    plan: dict[str, Any]

    # N06 Evidence 产物
    tool_results: list[dict[str, Any]]
    rag_hits_vector: list[dict[str, Any]]
    rag_hits_fts: list[dict[str, Any]]
    evidence_bundle: list[dict[str, Any]]

    # N07 Analysis 产物
    policy_report: dict[str, Any]
    risk_report: dict[str, Any]

    # N07 阶段受控回路字段
    analysis_attempt_count: int
    max_analysis_attempts: int
    evidence_query_history: list[dict[str, Any]]
    analysis_loop_status: dict[str, Any]

    # 运行期开关（由接口层注入，节点仅消费不修改）
    feature_enable_writeback: bool
    fault_injection: dict[str, bool]
    force_writeback_failure: bool

    # N08~N11 产物
    decision_draft: dict[str, Any]
    decision_final: dict[str, Any]
    self_critic_report: dict[str, Any]
    quality_report: dict[str, Any]
    route: str  # pass / degrade / reject / human_review
    writeback_result: dict[str, Any]
    audit_report: dict[str, Any]

    # 对外输出与错误
    answer_text: str
    errors: list[str]
