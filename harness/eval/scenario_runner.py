# Time: 2026-04-18 19:54
# Description: 执行 Harness 场景并记录 trace 快照，产出用于 Eval 与 Replay 的标准结果。
# Author: Feixue

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from harness.replay.trace_store import TRACE_REPLAY_STORE
from harness.scenarios.scenario_types import ScenarioCase
from src.agent.graph.builder import Orchestrator


@dataclass(frozen=True)
class ScenarioRunResult:
    """定义单条场景执行后的标准结果结构。"""

    scenario_id: str
    scenario_name: str
    trace_id: str
    expected_route: str
    actual_route: str
    latency_ms: float
    max_latency_ms: int
    route_matched: bool
    evidence_constraint_met: bool
    has_evidence_refs: bool
    output: dict[str, Any]


async def run_scenario_case(
    case: ScenarioCase,
    *,
    orchestrator: Orchestrator | None = None,
) -> ScenarioRunResult:
    """执行单条场景，并将输入输出快照写入 trace 存储。"""
    orchestrator = orchestrator or Orchestrator()

    # trace_id 保持全局唯一，便于后续 Replay 按 ID 精确重放。
    trace_id = f"{case.id}-{uuid.uuid4().hex[:10]}"
    state_input = {
        "trace_id": trace_id,
        "session_id": case.input.session_id,
        "work_order_id": case.input.work_order_id,
        "user_input": case.input.message,
        "feature_enable_writeback": bool(case.context.get("feature_enable_writeback", False)),
        "max_analysis_attempts": int(case.context.get("max_analysis_attempts", 2)),
        "fault_injection": _normalize_fault_injection(case.context.get("fault_injection", {})),
    }

    start = time.perf_counter()
    output = await orchestrator.run(state_input)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    actual_route = str(output.get("route", "human_review"))
    expected_route = case.expectations.route
    evidence_refs = list(output.get("decision_final", {}).get("evidence_refs", []))
    has_evidence_refs = len(evidence_refs) > 0

    # 证据约束与路由约束拆开计算，避免评测结果出现“到底哪条不通过”不清晰。
    if case.expectations.must_include_evidence_refs:
        evidence_constraint_met = has_evidence_refs
    else:
        evidence_constraint_met = True

    TRACE_REPLAY_STORE.save(
        trace_id=trace_id,
        state_input=state_input,
        output=output,
        latency_ms=latency_ms,
        scenario_id=case.id,
    )

    return ScenarioRunResult(
        scenario_id=case.id,
        scenario_name=case.name,
        trace_id=trace_id,
        expected_route=expected_route,
        actual_route=actual_route,
        latency_ms=latency_ms,
        max_latency_ms=case.expectations.max_latency_ms,
        route_matched=actual_route == expected_route,
        evidence_constraint_met=evidence_constraint_met,
        has_evidence_refs=has_evidence_refs,
        output=output,
    )


async def run_scenario_batch(
    cases: list[ScenarioCase],
    *,
    orchestrator: Orchestrator | None = None,
) -> list[ScenarioRunResult]:
    """按顺序执行场景批次，确保日志与 trace 输出稳定可追踪。"""
    orchestrator = orchestrator or Orchestrator()
    results: list[ScenarioRunResult] = []
    for case in cases:
        results.append(await run_scenario_case(case, orchestrator=orchestrator))
    return results


def _normalize_fault_injection(raw_value: object) -> dict[str, bool]:
    """清洗故障注入配置，保证下游只接收布尔开关。"""
    if not isinstance(raw_value, dict):
        return {}
    return {
        str(key): bool(value)
        for key, value in raw_value.items()
        if str(key).strip()
    }
