# Time: 2026-04-18 15:50
# Description: 提供 Redis 仓储的连接生命周期桩实现。
# Author: Feixue

from __future__ import annotations

from src.shared.logger import get_logger

logger = get_logger(__name__)


class RedisRepository:
    """Redis 仓储适配器（当前为桩实现）。"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connected = False

    async def connect(self) -> None:
        # 桩实现仅根据 URL 是否配置来模拟连接状态。
        self._connected = bool(self._url)
        logger.info(
            "redis_connect_stub",
            extra={"extra_fields": {"url_configured": bool(self._url)}},
        )

    async def disconnect(self) -> None:
        # 与真实驱动对齐：断开后状态必须回到未连接。
        self._connected = False
        logger.info("redis_disconnect_stub")

    async def ping(self) -> bool:
        """返回当前连接状态。"""
        return self._connected
