# Time: 2026-04-18 19:56
# Description: 负责执行合规检查与风险评估，并覆盖检索降级场景的风险升级与回路控制。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.agent.graph.state import GraphState
from src.shared.logger import get_logger

logger = get_logger(__name__)


async def run_analysis_subgraph(state: GraphState) -> GraphState:
    """执行 N07：PolicyChecker + RiskAssessor，并生成回路控制信号。"""
    evidence_bundle = list(state.get("evidence_bundle", []))
    tool_results = list(state.get("tool_results", []))

    policy_report = _policy_checker(evidence_bundle=evidence_bundle)
    risk_report = _risk_assessor(
        intent=state.get("intent", "general_consultation"),
        evidence_bundle=evidence_bundle,
        tool_results=tool_results,
        policy_report=policy_report,
    )

    current_attempt = _as_int(state.get("analysis_attempt_count", 0), default=0) + 1
    max_attempts = _safe_max_attempts(state.get("max_analysis_attempts", 2))
    needs_more_evidence = policy_report["next_action"] == "collect_more_evidence"
    can_retry = needs_more_evidence and current_attempt < max_attempts

    # 回路终止原因用于审计与测试定位，避免回边判定“黑箱化”。
    if not needs_more_evidence:
        termination_reason = "analysis_passed"
    elif can_retry:
        termination_reason = "awaiting_more_evidence"
    else:
        termination_reason = "max_attempts_reached"

    analysis_loop_status = {
        "needs_more_evidence": needs_more_evidence,
        "can_retry": can_retry,
        "attempt": current_attempt,
        "max_attempts": max_attempts,
        "termination_reason": termination_reason,
    }

    errors = list(state.get("errors", []))
    if not policy_report["passed"] and "analysis_policy_not_passed" not in errors:
        # 兜底逻辑：证据不足时记录分析失败信号，后续由质量门禁统一路由。
        errors.append("analysis_policy_not_passed")
    if (
        needs_more_evidence
        and not can_retry
        and "analysis_retry_budget_exhausted" not in errors
    ):
        # 当补证据预算耗尽时输出显式错误码，便于 N09 前做人工介入。
        errors.append("analysis_retry_budget_exhausted")

    logger.info(
        "analysis_summary",
        extra={
            "extra_fields": {
                "policy_passed": policy_report["passed"],
                "evidence_count": policy_report["evidence_count"],
                "risk_level": risk_report["risk_level"],
                "risk_flags": risk_report["risk_flags"],
                "attempt": current_attempt,
                "max_attempts": max_attempts,
                "can_retry": can_retry,
                "termination_reason": termination_reason,
            }
        },
    )

    return {
        "policy_report": policy_report,
        "risk_report": risk_report,
        "analysis_attempt_count": current_attempt,
        "analysis_loop_status": analysis_loop_status,
        "errors": errors,
    }


def _policy_checker(*, evidence_bundle: list[dict[str, Any]]) -> dict[str, Any]:
    """检查证据完整性与引用约束。"""
    evidence_count = len(evidence_bundle)
    missing_refs = [
        item.get("chunk_id", "unknown")
        for item in evidence_bundle
        if not item.get("evidence_ref")
    ]

    violations: list[str] = []
    if evidence_count == 0:
        violations.append("missing_evidence_bundle")
    if missing_refs:
        violations.append("missing_evidence_refs")

    passed = not violations
    return {
        "passed": passed,
        "evidence_count": evidence_count,
        "missing_ref_chunks": missing_refs,
        "violations": violations,
        "next_action": "proceed_to_decision" if passed else "collect_more_evidence",
    }


def _risk_assessor(
    *,
    intent: str,
    evidence_bundle: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    policy_report: dict[str, Any],
) -> dict[str, Any]:
    """根据证据质量、召回状态和业务意图计算风险等级。"""
    risk_flags: list[str] = []
    risk_level = "low"
    requires_human_review = False

    retrieval_summary = _last_retrieval_summary(tool_results)
    degrade_mode = str(retrieval_summary.get("degrade_mode", "dual_path"))
    if retrieval_summary.get("should_human_review", False):
        risk_level = "high"
        requires_human_review = True
        risk_flags.append("retrieval_pipeline_degraded_to_human_review")
    elif degrade_mode in {"fts_only", "vector_only"}:
        # 单路召回仍可继续，但为了防止证据偏置，需要提升风险并触发 degrade 路径。
        if risk_level in {"low", "medium"}:
            risk_level = "high"
        risk_flags.append("retrieval_single_path_degraded")

    if not evidence_bundle:
        risk_level = "high"
        requires_human_review = True
        risk_flags.append("empty_evidence_bundle")

    metadata_risk_tags = {
        item.get("metadata", {}).get("risk_tag")
        for item in evidence_bundle
        if isinstance(item, dict)
    }
    if "critical" in metadata_risk_tags:
        risk_level = "critical"
        requires_human_review = True
        risk_flags.append("critical_risk_tag_detected")
    elif "high" in metadata_risk_tags and risk_level != "critical":
        risk_level = "high"
        requires_human_review = True
        risk_flags.append("high_risk_tag_detected")

    if intent == "compliance_risk_check" and len(evidence_bundle) < 2 and risk_level == "low":
        risk_level = "medium"
        risk_flags.append("insufficient_evidence_for_compliance_check")

    if not policy_report.get("passed", False) and risk_level in {"low", "medium"}:
        risk_level = "high"
        requires_human_review = True
        risk_flags.append("policy_check_failed")

    return {
        "risk_level": risk_level,
        "risk_flags": sorted(set(risk_flags)),
        "requires_human_review": requires_human_review,
        "recommended_action": "human_review" if requires_human_review else "proceed",
    }


def _last_retrieval_summary(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    """读取最近一次检索流水线摘要，用于分析阶段降级判断。"""
    for item in reversed(tool_results):
        if item.get("tool") == "hybrid_retrieval_pipeline":
            return item
    return {}


def _as_int(value: Any, *, default: int) -> int:
    """解析整数值，避免脏值导致回路状态计算异常。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_max_attempts(value: Any) -> int:
    """保障最大尝试次数至少为 1，避免出现不可执行回路配置。"""
    parsed = _as_int(value, default=2)
    return max(parsed, 1)
