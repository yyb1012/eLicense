# Time: 2026-04-18 19:40
# Description: 校验 Orchestrator 在 N05~N11 阶段的主链路执行、受控补证据回路与审计输出。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph.builder import Orchestrator


def test_orchestrator_executes_n05_to_n11_chain() -> None:
    state = {
        "trace_id": "trace-int-001",
        "session_id": "S-INT-001",
        "work_order_id": "WO-INT-001",
        "user_input": "请审核证照并给出下一步",
    }

    output = asyncio.run(Orchestrator().run(state))

    assert output["intent"] == "license_review"
    assert output["plan"]["validation"]["is_valid"] is True
    assert len(output["evidence_bundle"]) > 0
    assert output["policy_report"]["passed"] is True
    assert output["analysis_attempt_count"] == 1
    assert len(output["evidence_query_history"]) == 1
    assert output["evidence_query_history"][0]["source"] == "user_input"
    assert output["risk_report"]["risk_level"] in {"low", "medium", "high", "critical"}
    assert output["decision_final"]["action"] in {"pass", "degrade", "reject", "human_review"}
    assert output["quality_report"]["version"] == "n09-quality-gate-v1"
    assert output["route"] in {"pass", "degrade", "reject", "human_review"}
    assert output["audit_report"]["version"] == "n11-audit-v1"
    assert output["audit_report"]["route"] == output["route"]
    assert output["answer_text"].startswith("[stub] request accepted:")


def test_orchestrator_retries_evidence_once_when_analysis_requests_more() -> None:
    state = {
        "trace_id": "trace-int-002",
        "session_id": "S-INT-002",
        "work_order_id": "WO-INT-002",
        "user_input": "xqzv-unknown-query",
        "max_analysis_attempts": 2,
    }

    output = asyncio.run(Orchestrator().run(state))

    assert output["analysis_attempt_count"] == 2
    assert len(output["evidence_query_history"]) == 2
    assert output["evidence_query_history"][0]["source"] == "user_input"
    assert output["evidence_query_history"][1]["source"] == "analysis_retry"
    assert output["analysis_loop_status"]["max_attempts"] == 2
    assert output["analysis_loop_status"]["can_retry"] is False
    assert output["policy_report"]["passed"] is True
    assert "evidence_retrieval_requires_human_review" in output["quality_report"]["blocking_signals"]
    assert output["route"] in {"pass", "degrade", "reject", "human_review"}
    assert output["audit_report"]["version"] == "n11-audit-v1"
    assert output["audit_report"]["route"] == output["route"]
