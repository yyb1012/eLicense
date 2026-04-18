# Time: 2026-04-18 21:10
# Description: 定义运维巡检与发布演练 API，提供触发、查询和审计追踪接口。
# Author: Feixue

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.application.services.inspection_service import InspectionService
from src.application.services.release_service import ReleaseService
from src.interfaces.api.dependencies import get_inspection_service, get_release_service
from src.shared.tracing import ensure_trace_id

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


class InspectionRunRequest(BaseModel):
    """手动巡检触发请求。"""

    mode: Literal["quick", "deep"] = "quick"
    metrics_override: dict[str, float | int] = Field(default_factory=dict)


class InspectionRunResponse(BaseModel):
    """手动巡检触发响应。"""

    trace_id: str
    report: dict[str, Any]


class InspectionReportsResponse(BaseModel):
    """巡检报告查询响应。"""

    trace_id: str
    reports: list[dict[str, Any]]


class InspectionIncidentsResponse(BaseModel):
    """异常事件查询响应。"""

    trace_id: str
    incidents: list[dict[str, Any]]


class ReleaseDrillRunRequest(BaseModel):
    """发布演练触发请求。"""

    eval_metrics_override: dict[str, float] = Field(default_factory=dict)
    inspection_metrics_override: dict[str, Any] = Field(default_factory=dict)
    consecutive_abnormal_alerts_override: int | None = Field(default=None, ge=0)


class ReleaseDrillRunResponse(BaseModel):
    """发布演练触发响应。"""

    trace_id: str
    release_report: dict[str, Any]


class ReleaseReportsResponse(BaseModel):
    """发布演练报告查询响应。"""

    trace_id: str
    reports: list[dict[str, Any]]


class RollbackReportsResponse(BaseModel):
    """回滚演练报告查询响应。"""

    trace_id: str
    rollbacks: list[dict[str, Any]]


@router.post("/inspection/run", response_model=InspectionRunResponse)
async def run_inspection(
    request: InspectionRunRequest,
    service: InspectionService = Depends(get_inspection_service),
) -> InspectionRunResponse:
    """手动触发一次巡检。"""
    trace_id = ensure_trace_id()
    report = await service.run_inspection(
        mode=request.mode,
        trigger="manual",
        trace_id=trace_id,
        metrics_override=request.metrics_override,
    )
    return InspectionRunResponse(trace_id=trace_id, report=report)


@router.get("/inspection/reports", response_model=InspectionReportsResponse)
async def get_inspection_reports(
    limit: int = Query(20, ge=1, le=200),
    service: InspectionService = Depends(get_inspection_service),
) -> InspectionReportsResponse:
    """获取巡检报告列表。"""
    trace_id = ensure_trace_id()
    return InspectionReportsResponse(trace_id=trace_id, reports=service.list_reports(limit=limit))


@router.get("/incidents", response_model=InspectionIncidentsResponse)
async def get_incidents(
    limit: int = Query(20, ge=1, le=200),
    service: InspectionService = Depends(get_inspection_service),
) -> InspectionIncidentsResponse:
    """获取异常事件台账列表。"""
    trace_id = ensure_trace_id()
    return InspectionIncidentsResponse(trace_id=trace_id, incidents=service.list_incidents(limit=limit))


@router.post("/release/drill/run", response_model=ReleaseDrillRunResponse)
async def run_release_drill(
    request: ReleaseDrillRunRequest,
    service: ReleaseService = Depends(get_release_service),
) -> ReleaseDrillRunResponse:
    """触发一次 N16 灰度发布与回滚演练。"""
    trace_id = ensure_trace_id()
    release_report = await service.run_release_drill(
        trace_id=trace_id,
        eval_metrics_override=request.eval_metrics_override,
        inspection_metrics_override=request.inspection_metrics_override,
        consecutive_abnormal_alerts_override=request.consecutive_abnormal_alerts_override,
    )
    return ReleaseDrillRunResponse(trace_id=trace_id, release_report=release_report)


@router.get("/release/reports", response_model=ReleaseReportsResponse)
async def get_release_reports(
    limit: int = Query(20, ge=1, le=200),
    service: ReleaseService = Depends(get_release_service),
) -> ReleaseReportsResponse:
    """查询发布演练报告列表。"""
    trace_id = ensure_trace_id()
    return ReleaseReportsResponse(trace_id=trace_id, reports=service.list_release_reports(limit=limit))


@router.get("/release/rollbacks", response_model=RollbackReportsResponse)
async def get_rollback_reports(
    limit: int = Query(20, ge=1, le=200),
    service: ReleaseService = Depends(get_release_service),
) -> RollbackReportsResponse:
    """查询回滚演练报告列表。"""
    trace_id = ensure_trace_id()
    return RollbackReportsResponse(trace_id=trace_id, rollbacks=service.list_rollback_reports(limit=limit))
