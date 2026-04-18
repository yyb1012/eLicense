# Time: 2026-04-18 19:05
# Description: 校验 Analysis 子图在合规校验与风险评估场景下的输出结构。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph.subgraphs.analysis_subgraph import run_analysis_subgraph


def test_analysis_subgraph_with_sufficient_evidence() -> None:
    state = {
        "intent": "license_review",
        "evidence_bundle": [
            {
                "chunk_id": "DOC-001",
                "evidence_ref": "chunk:DOC-001",
                "metadata": {"risk_tag": "normal"},
            }
        ],
        "tool_results": [],
        "errors": [],
    }

    patch = asyncio.run(run_analysis_subgraph(state))

    assert patch["policy_report"]["passed"] is True
    assert patch["policy_report"]["next_action"] == "proceed_to_decision"
    assert patch["risk_report"]["risk_level"] == "low"
    assert patch["risk_report"]["requires_human_review"] is False
    assert patch["errors"] == []


def test_analysis_subgraph_with_empty_evidence_requires_review() -> None:
    state = {
        "intent": "compliance_risk_check",
        "evidence_bundle": [],
        "tool_results": [
            {
                "tool": "hybrid_retrieval_pipeline",
                "should_human_review": True,
            }
        ],
        "errors": [],
    }

    patch = asyncio.run(run_analysis_subgraph(state))

    assert patch["policy_report"]["passed"] is False
    assert patch["risk_report"]["risk_level"] in {"high", "critical"}
    assert patch["risk_report"]["requires_human_review"] is True
    assert "analysis_policy_not_passed" in patch["errors"]
