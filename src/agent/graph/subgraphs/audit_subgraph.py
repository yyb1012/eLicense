# Time: 2026-04-18 19:36
# Description: 负责汇总路由与写回结果并输出审计日志，形成可追踪的执行快照。
# Author: Feixue

from __future__ import annotations

from datetime import datetime, timezone

from src.agent.graph.state import GraphState
from src.shared.logger import get_logger

logger = get_logger(__name__)


async def run_audit_subgraph(state: GraphState) -> GraphState:
    """执行 N11：汇总关键字段并输出结构化审计事件。"""
    route = str(state.get("route", "human_review"))
    risk_report = state.get("risk_report", {})
    quality_report = state.get("quality_report", {})
    writeback_result = state.get("writeback_result", {})
    errors = [str(item) for item in state.get("errors", [])]
    blocking_signals = _normalize_blocking_signals(quality_report)

    metrics = {
        "pipeline_latency_ms": -1,
        "token_cost": -1.0,
        "blocking_signal_count": len(blocking_signals),
        "error_count": len(errors),
        "writeback_status": str(writeback_result.get("status", "not_executed")),
        "collected_at_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    audit_report = {
        "version": "n11-audit-v1",
        "route": route,
        "risk_level": str(risk_report.get("risk_level", "unknown")),
        "blocking_signals": blocking_signals,
        "writeback_result": writeback_result,
        "errors": errors,
        "metrics": metrics,
    }

    logger.info(
        "audit_summary",
        extra={
            "extra_fields": {
                "route": audit_report["route"],
                "risk_level": audit_report["risk_level"],
                "blocking_signals": blocking_signals,
                "writeback_status": metrics["writeback_status"],
                "error_count": metrics["error_count"],
            }
        },
    )
    return {"audit_report": audit_report}


def _normalize_blocking_signals(quality_report: object) -> list[str]:
    """清洗阻断信号字段，保证审计输出结构稳定。"""
    if not isinstance(quality_report, dict):
        return []
    raw_signals = quality_report.get("blocking_signals", [])
    if not isinstance(raw_signals, list):
        return []
    return [str(item) for item in raw_signals if str(item).strip()]
