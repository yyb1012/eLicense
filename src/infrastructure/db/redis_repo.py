from __future__ import annotations

from src.shared.logger import get_logger

logger = get_logger(__name__)


class RedisRepository:
    """Minimal Redis adapter stub for N04."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connected = False

    async def connect(self) -> None:
        self._connected = bool(self._url)
        logger.info(
            "redis_connect_stub",
            extra={"extra_fields": {"url_configured": bool(self._url)}},
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("redis_disconnect_stub")

    async def ping(self) -> bool:
        return self._connected
