# Time: 2026-04-18 20:53
# Description: 校验巡检服务在异常场景下的 Agent 触发逻辑与开关降级行为。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.application.services.inspection_service import InspectionService


def test_inspection_service_runs_agent_when_enabled() -> None:
    """abnormal + 开关开启时应执行 Agent 归因并记录 incident。"""
    service = InspectionService(feature_enable_inspection_agent=True)

    report = asyncio.run(
        service.run_inspection(
            mode="quick",
            trigger="manual",
            trace_id="trace-inspection-enabled",
            metrics_override={
                "request_error_rate": 0.2,
                "latency_p99_ms": 9800,
            },
        )
    )

    assert report["status"] == "abnormal"
    assert report["agent_inspection"]["executed"] is True
    assert report["agent_inspection"]["skipped"] is False
    assert len(report["agent_inspection"]["possible_causes"]) > 0
    assert report["incident_ref"] is not None
    assert len(service.list_incidents()) == 1


def test_inspection_service_skips_agent_when_feature_disabled() -> None:
    """abnormal + 开关关闭时应跳过 Agent，但仍保留告警与 incident。"""
    service = InspectionService(feature_enable_inspection_agent=False)

    report = asyncio.run(
        service.run_inspection(
            mode="quick",
            trigger="manual",
            trace_id="trace-inspection-disabled",
            metrics_override={
                "request_error_rate": 0.2,
                "tool_failure_rate": 0.3,
            },
        )
    )

    assert report["status"] == "abnormal"
    assert report["agent_inspection"]["executed"] is False
    assert report["agent_inspection"]["skipped"] is True
    assert report["agent_inspection"]["reason"] == "feature_enable_inspection_agent_disabled"
    assert report["alert_event"] is not None
    assert report["incident_ref"] is not None
