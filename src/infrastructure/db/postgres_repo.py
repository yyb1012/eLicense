from __future__ import annotations

from src.shared.logger import get_logger

logger = get_logger(__name__)


class PostgresRepository:
    """Minimal PostgreSQL adapter stub for N04."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connected = False

    async def connect(self) -> None:
        self._connected = bool(self._dsn)
        logger.info(
            "postgres_connect_stub",
            extra={"extra_fields": {"dsn_configured": bool(self._dsn)}},
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("postgres_disconnect_stub")

    async def ping(self) -> bool:
        return self._connected
