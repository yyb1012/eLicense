# Time: 2026-04-18 19:05
# Description: 校验 Planner 子图的意图识别、计划生成与结构校验行为。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph.subgraphs.planner_subgraph import (
    build_plan,
    classify_intent,
    run_planner_subgraph,
    validate_plan,
)


def test_classify_intent_with_review_keyword() -> None:
    intent = classify_intent("请审核这张营业执照是否有效")
    assert intent == "license_review"


def test_build_plan_and_validate_plan() -> None:
    plan = build_plan(
        intent="material_completion",
        user_input="需要补充年检材料",
        session_id="S-100",
        work_order_id="WO-100",
    )
    validation = validate_plan(plan)

    assert validation["is_valid"] is True
    assert validation["step_count"] == 3
    assert not validation["missing_fields"]
    assert "retrieval_filter" in plan


def test_validate_plan_reports_missing_fields() -> None:
    validation = validate_plan({"intent": "license_review"})
    assert validation["is_valid"] is False
    assert "steps" in validation["missing_fields"]
    assert "constraints" in validation["missing_fields"]


def test_run_planner_subgraph_writes_intent_and_plan() -> None:
    state = {
        "trace_id": "trace-001",
        "session_id": "S-001",
        "work_order_id": "WO-001",
        "user_input": "请查询当前办理进度",
    }

    patch = asyncio.run(run_planner_subgraph(state))

    assert patch["intent"] == "status_inquiry"
    assert patch["plan"]["validation"]["is_valid"] is True
    assert patch["plan"]["constraints"]["require_evidence_refs"] is True
    assert patch["errors"] == []
