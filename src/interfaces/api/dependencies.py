# Time: 2026-04-18 23:26
# Description: 提供 FastAPI 路由依赖注入函数，集中暴露聊天、文档入库、巡检与发布服务。
# Author: Feixue

from __future__ import annotations

from fastapi import Request

from src.application.services.chat_service import ChatService
from src.application.services.document_ingest_service import DocumentIngestService
from src.application.services.inspection_service import InspectionService
from src.application.services.release_service import ReleaseService


def get_chat_service(request: Request) -> ChatService:
    """从应用状态中获取 ChatService 实例。"""
    return request.app.state.chat_service


def get_document_ingest_service(request: Request) -> DocumentIngestService:
    """从应用状态中获取 DocumentIngestService 实例。"""
    return request.app.state.document_ingest_service


def get_inspection_service(request: Request) -> InspectionService:
    """从应用状态中获取 InspectionService 实例。"""
    return request.app.state.inspection_service


def get_release_service(request: Request) -> ReleaseService:
    """从应用状态中获取 ReleaseService 实例。"""
    return request.app.state.release_service
