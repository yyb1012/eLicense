# Time: 2026-04-18 20:50
# Description: 提供巡检任务调度入口，封装快速巡检、深度巡检与日报汇总占位任务。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.application.services.inspection_service import InspectionService
from src.shared.tracing import new_trace_id


async def run_quick_inspection_job(service: InspectionService) -> dict[str, Any]:
    """快速巡检任务入口。

    设计边界：
    1. 该函数只负责触发服务，不承担调度框架职责。
    2. 真正的 cron/beat 集成将在后续阶段接入。
    """
    return await service.run_inspection(
        mode="quick",
        trigger="scheduler",
        trace_id=f"ops-quick-{new_trace_id()[:10]}",
    )


async def run_deep_inspection_job(service: InspectionService) -> dict[str, Any]:
    """深度巡检任务入口，用于低频更全面的规则检查。"""
    return await service.run_inspection(
        mode="deep",
        trigger="scheduler",
        trace_id=f"ops-deep-{new_trace_id()[:10]}",
    )


async def run_daily_summary_job(service: InspectionService) -> dict[str, Any]:
    """日报汇总任务入口。

    当前阶段只做汇总快照，后续可扩展为报表推送或入库归档。
    """
    return service.build_daily_summary()
