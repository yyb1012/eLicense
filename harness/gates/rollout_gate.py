# Time: 2026-04-18 21:02
# Description: 聚合评测门禁与巡检信号，输出灰度阶段是否可继续放量的统一判定结果。
# Author: Feixue

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RolloutGateThresholds:
    """灰度阶段门禁阈值。"""

    consecutive_abnormal_alerts_max: int = 1


def evaluate_rollout_stage_gate(
    *,
    eval_gate_result: dict[str, Any],
    latest_inspection_report: dict[str, Any],
    consecutive_abnormal_alerts: int,
    thresholds: RolloutGateThresholds | None = None,
) -> dict[str, Any]:
    """聚合发布门禁与巡检信号。

    设计原则：
    1. Eval Gate 和 Inspection Gate 都是硬约束，任一失败即阻断放量。
    2. 连续告警是独立阻断条件，避免“偶发恢复”掩盖持续性风险。
    3. 输出统一 checks 与 blocking_reasons，便于审计和自动化测试。
    """
    thresholds = thresholds or RolloutGateThresholds()

    eval_passed = bool(eval_gate_result.get("overall_passed", False))
    inspection_status = str(latest_inspection_report.get("status", "unknown"))
    inspection_normal = inspection_status == "normal"
    continuous_alerts_passed = (
        int(consecutive_abnormal_alerts) <= thresholds.consecutive_abnormal_alerts_max
    )

    checks = {
        "eval_gate": {
            "actual": eval_passed,
            "threshold": True,
            "passed": eval_passed,
        },
        "inspection_status": {
            "actual": inspection_status,
            "threshold": "normal",
            "passed": inspection_normal,
        },
        "consecutive_abnormal_alerts": {
            "actual": int(consecutive_abnormal_alerts),
            "threshold": thresholds.consecutive_abnormal_alerts_max,
            "passed": continuous_alerts_passed,
        },
    }

    blocking_reasons: list[str] = []
    if not eval_passed:
        blocking_reasons.append("eval_gate_failed")
    if not inspection_normal:
        blocking_reasons.append("inspection_status_abnormal")
    if not continuous_alerts_passed:
        blocking_reasons.append("consecutive_inspection_alerts")

    return {
        "overall_passed": len(blocking_reasons) == 0,
        "checks": checks,
        "blocking_reasons": blocking_reasons,
    }
