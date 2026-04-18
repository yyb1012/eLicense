# Time: 2026-04-18 19:55
# Description: 实现发布门禁判定，按主文档阈值校验评测指标是否允许进入下一阶段。
# Author: Feixue

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReleaseGateThresholds:
    """发布门禁阈值（对齐主文档 12.3 基线）。"""

    decision_accuracy_min: float = 0.90
    evidence_consistency_min: float = 0.95
    rejection_reasonableness_min: float = 0.90
    p95_latency_s_max: float = 6.0
    degrade_success_rate_min: float = 0.98


def evaluate_release_gate(
    eval_report: dict[str, Any],
    *,
    thresholds: ReleaseGateThresholds | None = None,
) -> dict[str, Any]:
    """根据评测报告计算每项门禁检查与总判定结果。"""
    thresholds = thresholds or ReleaseGateThresholds()
    metrics = eval_report.get("metrics", {})

    checks = {
        "decision_accuracy": {
            "actual": float(metrics.get("decision_accuracy", 0.0)),
            "threshold": thresholds.decision_accuracy_min,
            "passed": float(metrics.get("decision_accuracy", 0.0)) >= thresholds.decision_accuracy_min,
        },
        "evidence_consistency": {
            "actual": float(metrics.get("evidence_consistency", 0.0)),
            "threshold": thresholds.evidence_consistency_min,
            "passed": float(metrics.get("evidence_consistency", 0.0))
            >= thresholds.evidence_consistency_min,
        },
        "rejection_reasonableness": {
            "actual": float(metrics.get("rejection_reasonableness", 0.0)),
            "threshold": thresholds.rejection_reasonableness_min,
            "passed": float(metrics.get("rejection_reasonableness", 0.0))
            >= thresholds.rejection_reasonableness_min,
        },
        "p95_latency_s": {
            "actual": float(metrics.get("p95_latency_s", 9999.0)),
            "threshold": thresholds.p95_latency_s_max,
            "passed": float(metrics.get("p95_latency_s", 9999.0)) <= thresholds.p95_latency_s_max,
        },
        "degrade_success_rate": {
            "actual": float(metrics.get("degrade_success_rate", 0.0)),
            "threshold": thresholds.degrade_success_rate_min,
            "passed": float(metrics.get("degrade_success_rate", 0.0))
            >= thresholds.degrade_success_rate_min,
        },
    }

    return {
        "overall_passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
    }
