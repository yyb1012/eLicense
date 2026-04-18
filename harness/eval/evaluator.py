# Time: 2026-04-18 19:54
# Description: 聚合 Scenario 执行结果并计算发布门禁所需的核心评测指标。
# Author: Feixue

from __future__ import annotations

import math
from typing import Any

from harness.eval.scenario_runner import ScenarioRunResult


def evaluate_runs(results: list[ScenarioRunResult]) -> dict[str, Any]:
    """计算 N12 阶段基础指标，输出稳定的评测报告结构。"""
    if not results:
        raise ValueError("scenario results are empty")

    total = len(results)
    route_matched_count = sum(1 for item in results if item.route_matched)
    evidence_consistent_count = sum(1 for item in results if item.evidence_constraint_met)

    reject_cases = [
        item for item in results if item.expected_route in {"reject", "human_review"}
    ]
    if reject_cases:
        reject_reasonable_count = sum(
            1 for item in reject_cases if item.actual_route in {"reject", "human_review"}
        )
        rejection_reasonableness = reject_reasonable_count / len(reject_cases)
    else:
        rejection_reasonableness = 1.0

    degrade_cases = [
        item for item in results if item.expected_route in {"degrade", "human_review"}
    ]
    if degrade_cases:
        degrade_success_count = sum(
            1 for item in degrade_cases if item.actual_route in {"degrade", "human_review"}
        )
        degrade_success_rate = degrade_success_count / len(degrade_cases)
    else:
        degrade_success_rate = 1.0

    latencies_ms = sorted(item.latency_ms for item in results)
    p95_latency_s = round(_percentile(latencies_ms, 95) / 1000, 6)

    metrics = {
        "decision_accuracy": round(route_matched_count / total, 6),
        "evidence_consistency": round(evidence_consistent_count / total, 6),
        "rejection_reasonableness": round(rejection_reasonableness, 6),
        "p95_latency_s": p95_latency_s,
        "degrade_success_rate": round(degrade_success_rate, 6),
    }

    return {
        "summary": {
            "total_cases": total,
            "matched_cases": route_matched_count,
            "mismatched_cases": total - route_matched_count,
        },
        "metrics": metrics,
        "cases": [
            {
                "id": item.scenario_id,
                "name": item.scenario_name,
                "trace_id": item.trace_id,
                "expected_route": item.expected_route,
                "actual_route": item.actual_route,
                "latency_ms": item.latency_ms,
                "route_matched": item.route_matched,
                "evidence_constraint_met": item.evidence_constraint_met,
            }
            for item in results
        ],
    }


def _percentile(values: list[float], percentile: int) -> float:
    """计算分位数，采用线性插值，保证小样本时结果连续可解释。"""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])

    rank = (len(values) - 1) * (percentile / 100)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(values[lower])

    ratio = rank - lower
    return float(values[lower] + (values[upper] - values[lower]) * ratio)
