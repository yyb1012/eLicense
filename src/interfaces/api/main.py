from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.application.services.chat_service import ChatService
from src.infrastructure.db.postgres_repo import PostgresRepository
from src.infrastructure.db.redis_repo import RedisRepository
from src.interfaces.api.routes_chat import router as chat_router
from src.shared.config import get_settings
from src.shared.logger import configure_logging, get_logger
from src.shared.tracing import bind_trace_id, clear_trace_id, ensure_trace_id, new_trace_id

logger = get_logger(__name__)


def create_app() -> FastAPI:
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

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.postgres = PostgresRepository(settings.postgres_dsn)
    app.state.redis = RedisRepository(settings.redis_url)
    app.state.chat_service = ChatService()

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

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            content={
                "status": "ok",
                "trace_id": ensure_trace_id(),
            }
        )

    app.include_router(chat_router)
    return app


app = create_app()
