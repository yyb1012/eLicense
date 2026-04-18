# Time: 2026-04-18 19:40
# Description: 校验 N10~N11 路由分支下的写回与审计闭环行为。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph import builder as builder_mod
from src.agent.graph.builder import Orchestrator


async def _quality_gate_route_pass(_state):
    return {
        "quality_report": {
            "version": "n09-quality-gate-v1",
            "checks": {},
            "blocking_signals": [],
            "route_reason": "forced_for_test",
        },
        "route": "pass",
    }


async def _quality_gate_route_degrade(_state):
    return {
        "quality_report": {
            "version": "n09-quality-gate-v1",
            "checks": {},
            "blocking_signals": [],
            "route_reason": "forced_for_test",
        },
        "route": "degrade",
    }


def _base_state() -> dict[str, object]:
    return {
        "trace_id": "trace-wb-001",
        "session_id": "S-WB-001",
        "work_order_id": "WO-WB-001",
        "user_input": "请继续处理该工单",
    }


def test_pass_route_enters_writeback_and_outputs_result(monkeypatch) -> None:
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    monkeypatch.setattr(builder_mod, "_quality_gate_subgraph_entry", _quality_gate_route_pass)

    state = _base_state()
    state["feature_enable_writeback"] = True
    output = asyncio.run(Orchestrator().run(state))

    assert output["route"] == "pass"
    assert output["writeback_result"]["status"] == "succeeded_stub"
    assert output["writeback_result"]["code"] == "WRITEBACK_STUB_OK"
    assert output["audit_report"]["metrics"]["writeback_status"] == "succeeded_stub"


def test_writeback_is_skipped_when_feature_disabled(monkeypatch) -> None:
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    monkeypatch.setattr(builder_mod, "_quality_gate_subgraph_entry", _quality_gate_route_pass)

    state = _base_state()
    state["feature_enable_writeback"] = False
    output = asyncio.run(Orchestrator().run(state))

    assert output["route"] == "pass"
    assert output["writeback_result"]["status"] == "skipped_disabled"
    assert output["writeback_result"]["code"] == "WRITEBACK_DISABLED"
    assert output["audit_report"]["metrics"]["writeback_status"] == "skipped_disabled"


def test_non_pass_route_skips_writeback_but_still_audits(monkeypatch) -> None:
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    monkeypatch.setattr(builder_mod, "_quality_gate_subgraph_entry", _quality_gate_route_degrade)

    state = _base_state()
    state["feature_enable_writeback"] = True
    output = asyncio.run(Orchestrator().run(state))

    assert output["route"] == "degrade"
    assert "writeback_result" not in output
    assert output["audit_report"]["version"] == "n11-audit-v1"
    assert output["audit_report"]["metrics"]["writeback_status"] == "not_executed"
