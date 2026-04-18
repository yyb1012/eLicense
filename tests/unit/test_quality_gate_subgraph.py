# Time: 2026-04-18 22:12
# Description: 校验 N09 QualityGate 子图在不同决策与阻断信号下的路由裁决行为。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph.subgraphs.quality_gate_subgraph import run_quality_gate_subgraph


def test_quality_gate_returns_pass_for_clean_case() -> None:
    state = {
        "decision_final": {"version": "n08-decision-final-v1", "action": "pass"},
        "risk_report": {"risk_level": "low"},
        "self_critic_report": {"passed": True},
        "analysis_loop_status": {"needs_more_evidence": False, "can_retry": False},
        "errors": [],
    }

    patch = asyncio.run(run_quality_gate_subgraph(state))

    assert patch["route"] == "pass"
    assert patch["quality_report"]["checks"]["gate_1_contract"] is True


def test_quality_gate_returns_human_review_when_blocking_signal_exists() -> None:
    state = {
        "decision_final": {"version": "n08-decision-final-v1", "action": "pass"},
        "risk_report": {"risk_level": "low"},
        "self_critic_report": {"passed": True},
        "analysis_loop_status": {"needs_more_evidence": True, "can_retry": False},
        "errors": ["analysis_retry_budget_exhausted"],
    }

    patch = asyncio.run(run_quality_gate_subgraph(state))

    assert patch["route"] == "human_review"
    assert "analysis_retry_budget_exhausted" in patch["quality_report"]["blocking_signals"]


def test_quality_gate_returns_reject_for_reject_decision() -> None:
    state = {
        "decision_final": {"version": "n08-decision-final-v1", "action": "reject"},
        "risk_report": {"risk_level": "critical"},
        "self_critic_report": {"passed": True},
        "analysis_loop_status": {"needs_more_evidence": False, "can_retry": False},
        "errors": [],
    }

    patch = asyncio.run(run_quality_gate_subgraph(state))

    assert patch["route"] == "reject"
    assert patch["quality_report"]["route_reason"] in {"decision_final_reject", "critical_risk_level"}


def test_quality_gate_returns_degrade_for_high_risk_action() -> None:
    state = {
        "decision_final": {"version": "n08-decision-final-v1", "action": "degrade"},
        "risk_report": {"risk_level": "high"},
        "self_critic_report": {"passed": True},
        "analysis_loop_status": {"needs_more_evidence": False, "can_retry": False},
        "errors": [],
    }

    patch = asyncio.run(run_quality_gate_subgraph(state))

    assert patch["route"] == "degrade"
