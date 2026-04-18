# Time: 2026-04-18 19:58
# Description: 校验 N13 的 trace 重放与故障注入能力，确保降级路径与补偿结果可审计。
# Author: Feixue

from __future__ import annotations

import asyncio

from harness.eval.scenario_runner import run_scenario_case
from harness.fault.fault_runner import run_fault_case
from harness.replay.replay_runner import replay_trace
from harness.replay.trace_store import TRACE_REPLAY_STORE
from harness.scenarios.scenario_loader import load_scenarios
from src.agent.graph import builder as builder_mod
from src.agent.graph.builder import Orchestrator


def test_replay_trace_matches_key_fields(monkeypatch) -> None:
    """先执行场景再按 trace_id 重放，并校验关键字段一致。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    TRACE_REPLAY_STORE.clear()

    pass_case = load_scenarios()[0]
    run_result = asyncio.run(run_scenario_case(pass_case, orchestrator=Orchestrator()))
    replay_result = asyncio.run(replay_trace(run_result.trace_id, orchestrator=Orchestrator()))

    assert replay_result["trace_id"] == run_result.trace_id
    assert replay_result["all_matched"] is True
    assert replay_result["comparisons"]["route"]["matched"] is True
    assert replay_result["comparisons"]["decision"]["matched"] is True
    assert replay_result["comparisons"]["risk_level"]["matched"] is True
    assert replay_result["comparisons"]["writeback_status"]["matched"] is True


def test_fault_injection_retrieval_single_path_degrades(monkeypatch) -> None:
    """单路检索故障应触发 degrade，并保留审计结果。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)

    result = asyncio.run(run_fault_case("retrieval_single_path_failure", orchestrator=Orchestrator()))

    assert result["all_passed"] is True
    assert result["route"] == "degrade"
    assert result["writeback_status"] == "not_executed"
    assert result["checks"]["audit_present"] is True


def test_fault_injection_dual_path_goes_human_review(monkeypatch) -> None:
    """双路检索故障应进入 human_review 并输出阻断信号。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)

    result = asyncio.run(run_fault_case("retrieval_dual_path_failure", orchestrator=Orchestrator()))

    assert result["all_passed"] is True
    assert result["route"] == "human_review"
    assert "evidence_retrieval_requires_human_review" in result["errors"]
    assert result["checks"]["audit_present"] is True


def test_fault_injection_writeback_failure_compensates(monkeypatch) -> None:
    """写回故障应进入补偿分支并在审计中可见。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)

    result = asyncio.run(run_fault_case("writeback_failure", orchestrator=Orchestrator()))

    assert result["all_passed"] is True
    assert result["route"] == "pass"
    assert result["writeback_status"] == "compensated_stub"
    assert "writeback_compensated" in result["errors"]
    assert result["output"]["audit_report"]["metrics"]["writeback_status"] == "compensated_stub"
