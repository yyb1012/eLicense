# Time: 2026-04-18 20:49
# Description: 生成结构化告警事件并写入日志，作为外部告警系统接入前的分发占位层。
# Author: Feixue

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.shared.logger import get_logger

logger = get_logger(__name__)


def dispatch_alert_event(
    *,
    report_id: str,
    trace_id: str,
    mode: str,
    triggered_rules: list[str],
) -> dict[str, Any]:
    """分发告警事件（stub）。

    当前实现只做结构化日志输出，不对接真实短信/IM/邮件平台。
    这样可以在 N14 阶段先保证告警事件可追踪、可测试、可审计。
    """
    severity = _severity_from_rules(triggered_rules)
    event = {
        "alert_id": f"ALT-{uuid4().hex[:10]}",
        "report_id": report_id,
        "trace_id": trace_id,
        "mode": mode,
        "severity": severity,
        "channel": "stub_console",
        "triggered_rules": list(triggered_rules),
        "created_at_utc": datetime.now(tz=timezone.utc).isoformat(),
    }

    logger.warning(
        "inspection_alert_dispatched",
        extra={
            "extra_fields": {
                "alert_id": event["alert_id"],
                "report_id": report_id,
                "severity": severity,
                "triggered_rules": triggered_rules,
            }
        },
    )
    return event


def _severity_from_rules(triggered_rules: list[str]) -> str:
    """根据触发规则判定告警等级，便于值班快速分流处理优先级。"""
    if any(rule in {"writeback_failure_rate", "compensation_trigger_count"} for rule in triggered_rules):
        return "critical"
    if any(rule in {"request_error_rate", "latency_p99_ms"} for rule in triggered_rules):
        return "high"
    if len(triggered_rules) >= 3:
        return "high"
    return "medium"
