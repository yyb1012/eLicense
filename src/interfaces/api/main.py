# Time: 2026-04-19 00:38
# Description: 创建 FastAPI 应用并注册聊天、文档入库、巡检与发布演练路由，统一初始化依赖与生命周期。
# Author: Feixue

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.application.services.chat_service import ChatService
from src.application.services.document_ingest_service import DocumentIngestService
from src.application.services.inspection_service import InspectionService
from src.application.services.release_service import ReleaseService
from src.infrastructure.db.postgres_repo import PostgresRepository
from src.infrastructure.db.redis_repo import RedisRepository
from src.infrastructure.document.chunker import HeadingAwareChunker
from src.infrastructure.document.parser import build_default_document_parser_registry
from src.infrastructure.embedding.providers import build_embedding_provider
from src.infrastructure.ocr.adapters import build_default_ocr_adapter
from src.interfaces.api.routes_chat import router as chat_router
from src.interfaces.api.routes_ops import router as ops_router
from src.interfaces.api.routes_upload import router as upload_router
from src.shared.config import get_settings
from src.shared.logger import configure_logging, get_logger
from src.shared.tracing import bind_trace_id, clear_trace_id, ensure_trace_id, get_trace_id, new_trace_id

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用。"""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.postgres.connect()
        await app.state.redis.connect()
        logger.info("service_started")
        yield
        await app.state.postgres.disconnect()
        await app.state.redis.disconnect()
        logger.info("service_stopped")

    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.postgres = PostgresRepository(
        settings.postgres_dsn,
        sqlite_path=settings.ingest_store_sqlite_path,
    )
    app.state.redis = RedisRepository(settings.redis_url)

    embedding_provider = build_embedding_provider(
        provider_name=settings.ingest_embedding_provider,
        api_key=settings.model_api_key,
        timeout_seconds=settings.ingest_embedding_timeout_seconds,
        max_retries=settings.ingest_embedding_max_retries,
        batch_size=settings.ingest_embedding_batch_size,
        fallback_dimension=settings.ingest_embedding_dimension,
        embedding_version=settings.ingest_embedding_version,
    )

    app.state.chat_service = ChatService()
    app.state.document_ingest_service = DocumentIngestService(
        postgres_repo=app.state.postgres,
        parser_registry=build_default_document_parser_registry(),
        chunker=HeadingAwareChunker(
            max_tokens=settings.ingest_chunk_max_tokens,
            max_chars=settings.ingest_chunk_max_chars,
            overlap_tokens=settings.ingest_chunk_overlap,
        ),
        embedding_provider=embedding_provider,
        ocr_adapter=build_default_ocr_adapter(enabled=settings.ocr_enabled),
    )
    app.state.inspection_service = InspectionService(
        feature_enable_inspection_agent=settings.feature_enable_inspection_agent
    )
    app.state.release_service = ReleaseService(inspection_service=app.state.inspection_service)

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("x-trace-id", "").strip() or new_trace_id()
        bind_trace_id(trace_id)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed")
            raise
        finally:
            clear_trace_id()
        response.headers["x-trace-id"] = trace_id
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """统一异常返回格式，对齐文档约定的 ok/code/message/data/trace_id 结构。"""
        trace_id = get_trace_id() or "-"
        logger.exception(
            "unhandled_error",
            extra={"extra_fields": {"trace_id": trace_id}},
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "code": "INTERNAL_ERROR",
                "message": str(exc),
                "data": {},
                "trace_id": trace_id,
            },
        )

    @app.get("/health")
    async def health() -> JSONResponse:
        """提供基础存活检查与链路追踪验证。"""
        return JSONResponse(
            content={
                "status": "ok",
                "trace_id": ensure_trace_id(),
            }
        )

    app.include_router(chat_router)
    app.include_router(upload_router)
    app.include_router(ops_router)
    return app


app = create_app()
