# Time: 2026-04-18 19:56
# Description: 负责执行混合检索流水线，并在回放与故障注入场景下保持降级路径可复现。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.agent.graph.state import GraphState
from src.infrastructure.vector.hybrid_retriever import HybridRetriever
from src.infrastructure.vector.reranker import SimpleReranker
from src.infrastructure.vector.rrf_fuser import RrfFuser
from src.shared.logger import get_logger

logger = get_logger(__name__)


async def run_evidence_subgraph(
    state: GraphState,
    *,
    retriever: HybridRetriever | None = None,
    fuser: RrfFuser | None = None,
    reranker: SimpleReranker | None = None,
) -> GraphState:
    """执行 N06：Hard Filter -> Hybrid Recall -> Fusion -> Rerank -> Context Packing。"""
    retriever = retriever or HybridRetriever()
    fuser = fuser or RrfFuser()
    reranker = reranker or SimpleReranker()

    query, query_source = _build_retrieval_query(state)
    retrieval_filters = _extract_retrieval_filters(state)
    fault_injection = _extract_fault_injection(state)

    retrieval_result = await retriever.retrieve(
        query=query,
        filters=retrieval_filters,
        simulate_fail_fts=fault_injection["simulate_fail_fts"],
        simulate_fail_vector=fault_injection["simulate_fail_vector"],
    )
    fused_candidates = fuser.fuse(
        fts_hits=retrieval_result["fts_hits"],
        vector_hits=retrieval_result["vector_hits"],
        top_n_after_rrf=retriever.config.top_n_after_rrf,
    )
    rerank_result = reranker.rerank(
        query=query,
        candidates=fused_candidates,
        top_n_final=retriever.config.top_n_final,
    )

    reranked_items = rerank_result["items"]
    evidence_bundle = [
        _to_evidence_item(item)
        for item in reranked_items
        if item.get("selected_for_context", False)
    ]

    evidence_query_history = list(state.get("evidence_query_history", []))
    evidence_query_history.append(
        {
            "query": query,
            "source": query_source,
            "analysis_attempt_count": _as_int(state.get("analysis_attempt_count", 0), default=0),
        }
    )

    tool_results = list(state.get("tool_results", []))
    tool_results.append(
        {
            "tool": "hybrid_retrieval_pipeline",
            "query": query,
            "query_source": query_source,
            "filters": retrieval_filters,
            "degrade_mode": retrieval_result["degrade_mode"],
            "should_human_review": retrieval_result["should_human_review"],
            "fault_injection": fault_injection,
            "recall_latency_ms": retrieval_result["recall_latency_ms"],
            "rerank_latency_ms": rerank_result["latency_ms"],
            "counts": {
                "fts": len(retrieval_result["fts_hits"]),
                "vector": len(retrieval_result["vector_hits"]),
                "after_rrf": len(fused_candidates),
                "final_context": len(evidence_bundle),
                "query_history": len(evidence_query_history),
            },
        }
    )

    errors = list(state.get("errors", []))
    if retrieval_result["should_human_review"] and "evidence_retrieval_requires_human_review" not in errors:
        # 双路失败或双空召回时仅产出信号，route 仍由 N09 统一输出。
        errors.append("evidence_retrieval_requires_human_review")

    logger.info(
        "evidence_retrieval_summary",
        extra={
            "extra_fields": {
                "query_source": query_source,
                "degrade_mode": retrieval_result["degrade_mode"],
                "fts_count": len(retrieval_result["fts_hits"]),
                "vector_count": len(retrieval_result["vector_hits"]),
                "fused_count": len(fused_candidates),
                "final_context_count": len(evidence_bundle),
                "query_history_count": len(evidence_query_history),
                "recall_latency_ms": retrieval_result["recall_latency_ms"],
                "rerank_latency_ms": rerank_result["latency_ms"],
                "simulate_fail_fts": fault_injection["simulate_fail_fts"],
                "simulate_fail_vector": fault_injection["simulate_fail_vector"],
            }
        },
    )

    return {
        "tool_results": tool_results,
        "rag_hits_fts": retrieval_result["fts_hits"],
        "rag_hits_vector": retrieval_result["vector_hits"],
        "evidence_bundle": evidence_bundle,
        "evidence_query_history": evidence_query_history,
        "errors": errors,
    }


def _build_retrieval_query(state: GraphState) -> tuple[str, str]:
    """基于分析回路状态决定使用原始 query 还是补证据 query。"""
    base_query = str(state.get("user_input", "")).strip()
    policy_report = state.get("policy_report", {})
    analysis_attempt_count = _as_int(state.get("analysis_attempt_count", 0), default=0)

    # 仅在分析明确要求补证据且已经进入回路后才启用改写，避免主链路抖动。
    if (
        not isinstance(policy_report, dict)
        or policy_report.get("next_action") != "collect_more_evidence"
        or analysis_attempt_count <= 0
    ):
        return base_query, "user_input"

    retry_hints = _collect_retry_hints(state)
    refined_query = " ".join(part for part in [base_query, *retry_hints] if part).strip()
    if not refined_query:
        refined_query = "证照 审核 合规 风险 证据 引用"
    return refined_query, "analysis_retry"


def _collect_retry_hints(state: GraphState) -> list[str]:
    """汇总分析失败信号与过滤条件，生成受控补证据提示词。"""
    hints: list[str] = []
    intent = str(state.get("intent", ""))
    if intent == "license_review":
        hints.extend(["证照", "审核", "有效期"])
    elif intent == "compliance_risk_check":
        hints.extend(["合规", "风险", "整改"])
    elif intent == "material_completion":
        hints.extend(["补件", "材料完整性"])
    else:
        hints.extend(["证据", "引用"])

    policy_report = state.get("policy_report", {})
    if isinstance(policy_report, dict):
        violations = policy_report.get("violations", [])
        if isinstance(violations, list):
            for violation in violations:
                if violation == "missing_evidence_bundle":
                    hints.append("补充证据")
                elif violation == "missing_evidence_refs":
                    hints.append("证据引用")
                else:
                    hints.append(str(violation))

    risk_report = state.get("risk_report", {})
    risk_flag_hints = {
        "retrieval_pipeline_degraded_to_human_review": "双路召回",
        "empty_evidence_bundle": "补充证据",
        "critical_risk_tag_detected": "高风险标签",
        "high_risk_tag_detected": "高风险",
        "policy_check_failed": "合规校验",
    }
    if isinstance(risk_report, dict):
        risk_flags = risk_report.get("risk_flags", [])
        if isinstance(risk_flags, list):
            for risk_flag in risk_flags:
                hints.append(risk_flag_hints.get(str(risk_flag), str(risk_flag)))

    retrieval_filters = _extract_retrieval_filters(state)
    for value in retrieval_filters.values():
        if isinstance(value, (list, tuple, set)):
            hints.extend(str(item) for item in value)
        else:
            hints.append(str(value))

    normalized_hints: list[str] = []
    seen_hints: set[str] = set()
    for hint in hints:
        normalized = _normalize_hint(hint)
        if not normalized or normalized in seen_hints:
            continue
        seen_hints.add(normalized)
        normalized_hints.append(normalized)

    return normalized_hints[:8]


def _extract_retrieval_filters(state: GraphState) -> dict[str, Any]:
    """从计划中抽取硬过滤条件，避免将无关字段下发到召回层。"""
    plan = state.get("plan", {})
    if not isinstance(plan, dict):
        return {}

    raw_filters = plan.get("retrieval_filter", {})
    if not isinstance(raw_filters, dict):
        return {}

    return {
        key: value
        for key, value in raw_filters.items()
        if key in {"license_type", "current_node", "effective_date", "risk_tag"}
    }


def _extract_fault_injection(state: GraphState) -> dict[str, bool]:
    """提取检索故障注入开关，保证异常路径可被稳定回放。"""
    raw_value = state.get("fault_injection", {})
    if not isinstance(raw_value, dict):
        return {"simulate_fail_fts": False, "simulate_fail_vector": False}

    return {
        "simulate_fail_fts": bool(raw_value.get("simulate_fail_fts", False)),
        "simulate_fail_vector": bool(raw_value.get("simulate_fail_vector", False)),
    }


def _to_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    """将重排候选映射为 evidence_bundle 结构，统一证据引用格式。"""
    chunk_id = item.get("chunk_id", "unknown")
    return {
        "evidence_ref": f"chunk:{chunk_id}",
        "chunk_id": chunk_id,
        "content": item.get("content", ""),
        "metadata": item.get("metadata", {}),
        "rrf_score": item.get("rrf_score", 0.0),
        "rerank_score": item.get("rerank_score", 0.0),
        "final_rank": item.get("final_rank", 0),
    }


def _normalize_hint(value: Any) -> str:
    """将提示词归一化为稳定 token，避免查询改写重复堆叠。"""
    normalized = str(value).replace("_", " ").strip()
    return " ".join(normalized.split())


def _as_int(value: Any, *, default: int) -> int:
    """以安全方式解析整数配置，保证回路计数不会因脏值中断。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
