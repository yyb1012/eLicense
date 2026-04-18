# Time: 2026-04-18 22:12
# Description: 校验 N08 Decision 子图在草案生成、自检与修订环节的输出稳定性。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph.subgraphs.decision_subgraph import run_decision_subgraph


def test_decision_subgraph_outputs_pass_for_low_risk_case() -> None:
    state = {
        "policy_report": {"passed": True},
        "risk_report": {"risk_level": "low"},
        "evidence_bundle": [{"evidence_ref": "chunk:DOC-001"}],
        "analysis_loop_status": {"needs_more_evidence": False, "can_retry": False},
    }

    patch = asyncio.run(run_decision_subgraph(state))

    assert patch["decision_draft"]["action"] == "pass"
    assert patch["self_critic_report"]["passed"] is True
    assert patch["decision_final"]["action"] == "pass"


def test_decision_subgraph_outputs_reject_for_critical_risk() -> None:
    state = {
        "policy_report": {"passed": True},
        "risk_report": {"risk_level": "critical"},
        "evidence_bundle": [{"evidence_ref": "chunk:DOC-005"}],
        "analysis_loop_status": {"needs_more_evidence": False, "can_retry": False},
    }

    patch = asyncio.run(run_decision_subgraph(state))

    assert patch["decision_draft"]["action"] == "reject"
    assert patch["decision_final"]["action"] == "reject"


def test_decision_subgraph_marks_missing_evidence_refs() -> None:
    state = {
        "policy_report": {"passed": False},
        "risk_report": {"risk_level": "high"},
        "evidence_bundle": [{}],
        "analysis_loop_status": {"needs_more_evidence": True, "can_retry": False},
    }

    patch = asyncio.run(run_decision_subgraph(state))

    assert "decision_missing_evidence_refs" in patch["self_critic_report"]["issues"]
    assert patch["decision_final"]["action"] == "human_review"
