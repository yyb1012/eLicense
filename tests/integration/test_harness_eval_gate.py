# Time: 2026-04-18 19:58
# Description: 校验 N12 场景批评测与发布门禁判定链路，确保四类路由样例可回归。
# Author: Feixue

from __future__ import annotations

import asyncio

from harness.eval.evaluator import evaluate_runs
from harness.eval.scenario_runner import run_scenario_batch
from harness.gates.release_gate import evaluate_release_gate
from harness.replay.trace_store import TRACE_REPLAY_STORE
from harness.scenarios.scenario_loader import load_scenarios
from src.agent.graph import builder as builder_mod
from src.agent.graph.builder import Orchestrator


def test_harness_scenario_eval_and_gate(monkeypatch) -> None:
    """执行 N12 最小闭环：Scenario -> Eval -> Release Gate。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    TRACE_REPLAY_STORE.clear()

    cases = load_scenarios()
    results = asyncio.run(run_scenario_batch(cases, orchestrator=Orchestrator()))

    assert len(results) == 4
    assert {item.expected_route for item in results} == {
        "pass",
        "degrade",
        "reject",
        "human_review",
    }
    assert all(item.route_matched for item in results)
    assert all(item.latency_ms <= item.max_latency_ms for item in results)

    eval_report = evaluate_runs(results)
    metrics = eval_report["metrics"]
    assert metrics["decision_accuracy"] >= 0.90
    assert metrics["evidence_consistency"] >= 0.95
    assert metrics["rejection_reasonableness"] >= 0.90
    assert metrics["p95_latency_s"] <= 6.0
    assert metrics["degrade_success_rate"] >= 0.98

    gate = evaluate_release_gate(eval_report)
    assert gate["overall_passed"] is True
