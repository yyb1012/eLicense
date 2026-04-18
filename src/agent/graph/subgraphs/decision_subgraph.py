# Time: 2026-04-18 22:05
# Description: 负责生成决策草案并执行自检修订，输出可供质量门禁消费的最终决策对象。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.agent.graph.state import GraphState
from src.shared.logger import get_logger

logger = get_logger(__name__)


async def run_decision_subgraph(state: GraphState) -> GraphState:
    """执行 N08：Decision + Self-Critic。"""
    decision_draft = _build_decision_draft(state)
    self_critic_report = _self_critic(state=state, decision_draft=decision_draft)
    decision_final = _revise_decision(draft=decision_draft, critic_report=self_critic_report)

    logger.info(
        "decision_summary",
        extra={
            "extra_fields": {
                "draft_action": decision_draft["action"],
                "final_action": decision_final["action"],
                "self_critic_passed": self_critic_report["passed"],
                "issues": self_critic_report["issues"],
            }
        },
    )

    return {
        "decision_draft": decision_draft,
        "self_critic_report": self_critic_report,
        "decision_final": decision_final,
    }


def _build_decision_draft(state: GraphState) -> dict[str, Any]:
    """基于 N05~N07 产物生成可解释的初稿决策。"""
    policy_report = state.get("policy_report", {})
    risk_report = state.get("risk_report", {})
    evidence_bundle = list(state.get("evidence_bundle", []))
    loop_status = state.get("analysis_loop_status", {})

    policy_passed = bool(policy_report.get("passed", False))
    risk_level = str(risk_report.get("risk_level", "unknown"))
    evidence_refs = [
        item.get("evidence_ref", "")
        for item in evidence_bundle
        if isinstance(item, dict) and item.get("evidence_ref")
    ]
    needs_more_evidence = bool(loop_status.get("needs_more_evidence", False))
    retry_budget_exhausted = (
        needs_more_evidence and not bool(loop_status.get("can_retry", False))
    )

    rationale: list[str] = []
    if policy_passed:
        rationale.append("policy_passed")
    else:
        rationale.append("policy_not_passed")
    rationale.append(f"risk_level={risk_level}")
    rationale.append(f"evidence_refs={len(evidence_refs)}")

    if retry_budget_exhausted:
        action = "human_review"
        confidence = 0.35
        rationale.append("retry_budget_exhausted")
    elif not policy_passed:
        action = "human_review"
        confidence = 0.45
    elif risk_level == "critical":
        action = "reject"
        confidence = 0.9
    elif risk_level == "high":
        action = "degrade"
        confidence = 0.68
    else:
        action = "pass"
        confidence = 0.82

    return {
        "version": "n08-decision-draft-v1",
        "action": action,
        "confidence": round(confidence, 2),
        "rationale": rationale,
        "evidence_refs": evidence_refs,
        "risk_level": risk_level,
        "policy_passed": policy_passed,
    }


def _self_critic(*, state: GraphState, decision_draft: dict[str, Any]) -> dict[str, Any]:
    """校验决策初稿是否与风险、证据与分析回路信号一致。"""
    issues: list[str] = []
    suggestion = decision_draft["action"]

    if not decision_draft.get("evidence_refs"):
        issues.append("decision_missing_evidence_refs")

    if decision_draft["risk_level"] == "critical" and decision_draft["action"] != "reject":
        issues.append("critical_risk_must_reject")
        suggestion = "reject"

    if (not decision_draft["policy_passed"]) and decision_draft["action"] == "pass":
        issues.append("policy_failed_cannot_pass")
        suggestion = "human_review"

    loop_status = state.get("analysis_loop_status", {})
    if (
        isinstance(loop_status, dict)
        and loop_status.get("needs_more_evidence", False)
        and not loop_status.get("can_retry", False)
        and decision_draft["action"] == "pass"
    ):
        issues.append("retry_budget_exhausted_cannot_pass")
        suggestion = "human_review"

    passed = not issues
    return {
        "version": "n08-self-critic-v1",
        "passed": passed,
        "issues": issues,
        "suggested_action": suggestion,
    }


def _revise_decision(
    *,
    draft: dict[str, Any],
    critic_report: dict[str, Any],
) -> dict[str, Any]:
    """根据自检结果输出最终决策，保留初稿与修订差异。"""
    final_action = draft["action"]
    revised = False
    if not critic_report["passed"]:
        final_action = critic_report["suggested_action"]
        revised = final_action != draft["action"]

    return {
        "version": "n08-decision-final-v1",
        "action": final_action,
        "confidence": draft["confidence"],
        "rationale": list(draft["rationale"]),
        "evidence_refs": list(draft["evidence_refs"]),
        "risk_level": draft["risk_level"],
        "policy_passed": draft["policy_passed"],
        "revised_by_self_critic": revised,
    }
