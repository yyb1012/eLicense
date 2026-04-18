# Time: 2026-04-18 21:22
# Description: 校验 N16 发布演练服务在放量推进、阻断与回滚触发下的行为与审计字段稳定性。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph import builder as builder_mod
from src.application.services.inspection_service import InspectionService
from src.application.services.release_service import ReleaseService


def _passing_eval_metrics() -> dict[str, float]:
    return {
        "decision_accuracy": 0.99,
        "evidence_consistency": 0.99,
        "rejection_reasonableness": 0.99,
        "p95_latency_s": 0.5,
        "degrade_success_rate": 0.99,
    }


def test_release_drill_passes_all_rollout_stages(monkeypatch) -> None:
    """全部门禁通过时应按 5->20->50->100 完成放量。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    inspection_service = InspectionService(feature_enable_inspection_agent=False)
    release_service = ReleaseService(inspection_service=inspection_service)

    report = asyncio.run(
        release_service.run_release_drill(
            trace_id="trace-release-pass",
            eval_metrics_override=_passing_eval_metrics(),
            inspection_metrics_override={
                "quick": {"request_error_rate": 0.001},
                "deep": {"request_error_rate": 0.001},
            },
        )
    )

    assert report["overall_status"] == "passed"
    assert [stage["traffic_percent"] for stage in report["stages"]] == [5, 20, 50, 100]
    assert [stage["status"] for stage in report["stages"]] == [
        "passed",
        "passed",
        "passed",
        "passed",
    ]
    assert report["rollback_ref"] is None


def test_release_drill_blocks_and_rolls_back_on_decision_accuracy(monkeypatch) -> None:
    """准确率跌破阈值应阻断并触发回滚。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    inspection_service = InspectionService(feature_enable_inspection_agent=False)
    release_service = ReleaseService(inspection_service=inspection_service)

    report = asyncio.run(
        release_service.run_release_drill(
            trace_id="trace-release-acc-fail",
            eval_metrics_override={
                **_passing_eval_metrics(),
                "decision_accuracy": 0.2,
            },
        )
    )

    assert report["overall_status"] == "rolled_back"
    assert report["stages"][0]["status"] == "blocked"
    rollback = report["rollback_report"]
    assert rollback["executed"] is True
    assert "decision_accuracy_below_threshold" in rollback["trigger_reasons"]
    assert [item["order"] for item in rollback["steps"]] == [1, 2, 3]


def test_release_drill_rolls_back_when_writeback_failure_rate_exceeded(monkeypatch) -> None:
    """写回失败率超阈值应在后续阶段阻断，并把已通过阶段标记为 rolled_back。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    inspection_service = InspectionService(feature_enable_inspection_agent=False)
    release_service = ReleaseService(inspection_service=inspection_service)

    report = asyncio.run(
        release_service.run_release_drill(
            trace_id="trace-release-writeback-fail",
            eval_metrics_override=_passing_eval_metrics(),
            inspection_metrics_override={
                "quick": {"writeback_failure_rate": 0.0},
                "deep": {"writeback_failure_rate": 0.4},
            },
        )
    )

    assert report["overall_status"] == "rolled_back"
    statuses = [stage["status"] for stage in report["stages"]]
    assert statuses[0] == "rolled_back"
    assert statuses[1] == "rolled_back"
    assert statuses[2] == "blocked"
    rollback = report["rollback_report"]
    assert "writeback_failure_rate_exceeded" in rollback["trigger_reasons"]


def test_release_drill_rolls_back_on_consecutive_alerts(monkeypatch) -> None:
    """连续巡检告警超阈值应触发回滚。"""
    monkeypatch.setattr(builder_mod, "StateGraph", None)
    inspection_service = InspectionService(feature_enable_inspection_agent=False)
    release_service = ReleaseService(inspection_service=inspection_service)

    report = asyncio.run(
        release_service.run_release_drill(
            trace_id="trace-release-alert-fail",
            eval_metrics_override=_passing_eval_metrics(),
            consecutive_abnormal_alerts_override=3,
        )
    )

    assert report["overall_status"] == "rolled_back"
    rollback = report["rollback_report"]
    assert "consecutive_inspection_alerts" in rollback["trigger_reasons"]
    assert rollback["manual_confirmation_points"] == [
        "rollback_to_last_stable_version",
        "record_incident_review_entry",
    ]
