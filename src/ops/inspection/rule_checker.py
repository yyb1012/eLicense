# Time: 2026-04-18 21:42
# Description: 定义巡检规则阈值并执行硬规则判定，输出可审计的结构化规则检查报告。
# Author: Feixue

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.shared.utils import safe_float, safe_int


@dataclass(frozen=True)
class InspectionThresholds:
    """巡检硬阈值配置，所有阈值都可用于规则巡检与回归测试。"""

    request_error_rate_max: float = 0.05
    latency_p95_ms_max: float = 6000.0
    latency_p99_ms_max: float = 8000.0
    tool_failure_rate_max: float = 0.10
    empty_recall_rate_max: float = 0.03
    writeback_failure_rate_max: float = 0.02
    compensation_trigger_count_max: int = 3
    human_review_ratio_max: float = 0.35
    # TODO(N07A): 接入 OCR 巡检指标 — ocr_avg_latency_ms, ocr_failure_rate, ocr_low_confidence_ratio


def evaluate_metrics_rules(
    metrics: dict[str, Any],
    *,
    thresholds: InspectionThresholds | None = None,
) -> dict[str, Any]:
    """执行规则巡检并输出检查结果。

    设计要点：
    1. 规则巡检是 N14 的硬门禁，必须与 Agent 巡检解耦，保证即使 Agent 关闭也可稳定运行。
    2. 每个检查项都返回 actual/threshold/passed 三元组，便于审计和事件复盘。
    3. status 只由硬规则决定：任一检查不通过即 abnormal。
    """
    thresholds = thresholds or InspectionThresholds()
    normalized = _normalize_metrics(metrics)

    checks = {
        "request_error_rate": _max_check(
            actual=normalized["request_error_rate"],
            threshold=thresholds.request_error_rate_max,
        ),
        "latency_p95_ms": _max_check(
            actual=normalized["latency_p95_ms"],
            threshold=thresholds.latency_p95_ms_max,
        ),
        "latency_p99_ms": _max_check(
            actual=normalized["latency_p99_ms"],
            threshold=thresholds.latency_p99_ms_max,
        ),
        "tool_failure_rate": _max_check(
            actual=normalized["tool_failure_rate"],
            threshold=thresholds.tool_failure_rate_max,
        ),
        "empty_recall_rate": _max_check(
            actual=normalized["empty_recall_rate"],
            threshold=thresholds.empty_recall_rate_max,
        ),
        "writeback_failure_rate": _max_check(
            actual=normalized["writeback_failure_rate"],
            threshold=thresholds.writeback_failure_rate_max,
        ),
        "compensation_trigger_count": _max_check(
            actual=float(normalized["compensation_trigger_count"]),
            threshold=float(thresholds.compensation_trigger_count_max),
        ),
        "human_review_ratio": _max_check(
            actual=normalized["human_review_ratio"],
            threshold=thresholds.human_review_ratio_max,
        ),
    }

    triggered_rules = [key for key, detail in checks.items() if not detail["passed"]]
    status = "normal" if not triggered_rules else "abnormal"

    return {
        "status": status,
        "checks": checks,
        "triggered_rules": triggered_rules,
        "summary": {
            "passed_count": sum(1 for detail in checks.values() if detail["passed"]),
            "failed_count": len(triggered_rules),
            "total_count": len(checks),
        },
    }


def _normalize_metrics(raw_metrics: dict[str, Any]) -> dict[str, float | int]:
    """将指标输入归一化为固定字段，避免上游缺字段导致规则巡检中断。"""
    metrics = dict(raw_metrics)
    return {
        "request_error_rate": safe_float(metrics.get("request_error_rate", 0.0)),
        "latency_p95_ms": safe_float(metrics.get("latency_p95_ms", 0.0)),
        "latency_p99_ms": safe_float(metrics.get("latency_p99_ms", 0.0)),
        "tool_failure_rate": safe_float(metrics.get("tool_failure_rate", 0.0)),
        "empty_recall_rate": safe_float(metrics.get("empty_recall_rate", 0.0)),
        "writeback_failure_rate": safe_float(metrics.get("writeback_failure_rate", 0.0)),
        "compensation_trigger_count": safe_int(metrics.get("compensation_trigger_count", 0)),
        "human_review_ratio": safe_float(metrics.get("human_review_ratio", 0.0)),
    }


def _max_check(*, actual: float, threshold: float) -> dict[str, Any]:
    """最大值阈值检查：actual <= threshold 视为通过。"""
    return {
        "actual": round(actual, 6),
        "threshold": round(threshold, 6),
        "passed": actual <= threshold,
    }


def _as_float(value: Any) -> float:
    """安全解析浮点数，异常时回退 0.0，保证巡检链路可持续执行。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    """安全解析整数，异常时回退 0。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
