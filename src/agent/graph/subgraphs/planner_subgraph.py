# Time: 2026-04-18 19:05
# Description: 负责识别用户意图并产出可校验且可过滤检索范围的执行计划草案。
# Author: Feixue

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.agent.graph.state import GraphState
from src.shared.logger import get_logger

logger = get_logger(__name__)

# 规则按优先级排序：越靠前越先命中，避免多关键词时意图歧义。
_INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("material_completion", ("补件", "补充", "缺失", "材料", "missing")),
    ("compliance_risk_check", ("风险", "违规", "合规", "risk", "compliance")),
    ("status_inquiry", ("进度", "状态", "查询", "status")),
    ("license_review", ("审核", "核验", "审查", "review", "审批")),
]

_STEP_TEMPLATES: dict[str, list[str]] = {
    "material_completion": [
        "确认当前缺失材料与补件目标",
        "生成补件清单并标记优先级",
        "等待 Evidence 子图补充证据来源",
    ],
    "compliance_risk_check": [
        "识别合规范围与风险维度",
        "准备风险核查问题列表",
        "等待 Evidence 子图回填证据后进入分析",
    ],
    "status_inquiry": [
        "确认查询对象与目标状态",
        "准备状态查询参数",
        "等待 Evidence 子图返回系统证据",
    ],
    "license_review": [
        "识别证照类型与审查目标",
        "生成审查步骤草案",
        "等待 Evidence 子图回填证据引用",
    ],
    "general_consultation": [
        "抽取用户问题中的核心目标",
        "生成可执行的通用处理步骤",
        "等待后续子图补充证据与分析结果",
    ],
}


def classify_intent(message: str) -> str:
    """根据关键词做最小可解释意图识别。"""
    normalized = message.strip().lower()
    if not normalized:
        return "general_consultation"

    for intent, keywords in _INTENT_RULES:
        if _contains_any(normalized, keywords):
            return intent
    return "general_consultation"


def build_plan(*, intent: str, user_input: str, session_id: str, work_order_id: str) -> dict[str, Any]:
    """根据意图生成后续子图可消费的执行计划草案。"""
    step_titles = _STEP_TEMPLATES.get(intent, _STEP_TEMPLATES["general_consultation"])
    steps: list[dict[str, Any]] = []
    for index, title in enumerate(step_titles, start=1):
        steps.append(
            {
                "id": f"P{index:02d}",
                "name": title,
                "status": "pending",
            }
        )

    objective = user_input.strip() or "clarify_user_request"
    retrieval_filter = _infer_retrieval_filter(intent=intent, user_input=user_input)
    return {
        "version": "n05-planner-v2",
        "intent": intent,
        "objective": objective,
        "session_id": session_id,
        "work_order_id": work_order_id,
        "steps": steps,
        "retrieval_filter": retrieval_filter,
        "constraints": {
            "require_evidence_refs": True,
            "route_owned_by": "quality_gate_subgraph",
        },
    }


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """校验计划结构，保证后续子图可以稳定复用。"""
    required_fields = (
        "version",
        "intent",
        "objective",
        "steps",
        "retrieval_filter",
        "constraints",
    )
    missing_fields = [field for field in required_fields if field not in plan]

    steps = plan.get("steps")
    invalid_step_indexes: list[int] = []
    if isinstance(steps, list):
        for index, step in enumerate(steps):
            if not _valid_step(step):
                invalid_step_indexes.append(index)
    else:
        invalid_step_indexes.append(-1)

    retrieval_filter = plan.get("retrieval_filter")
    invalid_filter_keys = []
    if isinstance(retrieval_filter, dict):
        invalid_filter_keys = [
            key
            for key in retrieval_filter.keys()
            if key not in {"license_type", "current_node", "effective_date", "risk_tag"}
        ]
    else:
        invalid_filter_keys.append("retrieval_filter_not_dict")

    is_valid = not missing_fields and not invalid_step_indexes and not invalid_filter_keys
    return {
        "is_valid": is_valid,
        "missing_fields": missing_fields,
        "invalid_step_indexes": invalid_step_indexes,
        "invalid_filter_keys": invalid_filter_keys,
        "step_count": len(steps) if isinstance(steps, list) else 0,
    }


async def run_planner_subgraph(state: GraphState) -> GraphState:
    """执行 Planner 子图并写入 intent/plan 字段。"""
    intent = classify_intent(state.get("user_input", ""))
    plan = build_plan(
        intent=intent,
        user_input=state.get("user_input", ""),
        session_id=state.get("session_id", ""),
        work_order_id=state.get("work_order_id", ""),
    )
    validation = validate_plan(plan)

    errors = list(state.get("errors", []))
    if not validation["is_valid"]:
        # 降级策略：计划结构异常时仍输出兜底计划，避免主链路直接中断。
        logger.warning(
            "planner_plan_invalid_fallback_applied",
            extra={"extra_fields": {"validation": validation}},
        )
        errors.append("planner_plan_validation_failed")
        plan = _fallback_plan(intent=intent, user_input=state.get("user_input", ""))
        validation = validate_plan(plan)

    plan["validation"] = validation
    return {
        "intent": intent,
        "plan": plan,
        "errors": errors,
    }


def _fallback_plan(*, intent: str, user_input: str) -> dict[str, Any]:
    """Planner 兜底计划，确保 N05 阶段接口契约持续可用。"""
    objective = user_input.strip() or "clarify_user_request"
    return {
        "version": "n05-planner-fallback-v2",
        "intent": intent or "general_consultation",
        "objective": objective,
        "steps": [
            {"id": "P01", "name": "回退到基础计划并等待后续子图补证", "status": "pending"},
        ],
        "retrieval_filter": {},
        "constraints": {
            "require_evidence_refs": True,
            "route_owned_by": "quality_gate_subgraph",
        },
    }


def _infer_retrieval_filter(*, intent: str, user_input: str) -> dict[str, Any]:
    """按意图和关键词推断检索硬过滤条件。"""
    normalized = user_input.lower()
    filters: dict[str, Any] = {}

    if intent == "license_review" or "营业执照" in user_input:
        filters["license_type"] = "营业执照"

    if intent == "material_completion":
        filters["current_node"] = "补件"

    if intent == "status_inquiry":
        filters["current_node"] = ["处理中", "初审", "复审", "补件"]

    if intent == "compliance_risk_check" or "风险" in user_input or "违规" in user_input:
        filters["risk_tag"] = ["high", "critical"]

    if "过期" in user_input or "有效期" in user_input:
        filters.setdefault("risk_tag", ["high", "critical"])

    if "复审" in user_input:
        filters["current_node"] = "复审"

    if "初审" in user_input:
        filters["current_node"] = "初审"

    if "复核" in user_input:
        filters["current_node"] = "复核"

    if isinstance(filters.get("risk_tag"), list):
        filters["risk_tag"] = sorted(set(filters["risk_tag"]))

    return filters


def _contains_any(text: str, candidates: Iterable[str]) -> bool:
    """判断文本是否包含任意候选关键词。"""
    return any(token in text for token in candidates)


def _valid_step(step: Any) -> bool:
    """校验步骤结构，避免后续节点解析失败。"""
    if not isinstance(step, dict):
        return False
    required_fields = ("id", "name", "status")
    return all(step.get(field) for field in required_fields)
