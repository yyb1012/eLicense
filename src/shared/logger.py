# Time: 2026-04-18 15:50
# Description: 配置带 trace_id 上下文的 JSON 日志输出。
# Author: Feixue

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.shared.tracing import get_trace_id

_LOGGING_READY = False


class TraceContextFilter(logging.Filter):
    """向日志记录注入 trace_id 与扩展字段容器。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        if not hasattr(record, "extra_fields"):
            record.extra_fields = {}
        return True


class JsonFormatter(logging.Formatter):
    """将日志格式化为统一 JSON 结构。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """初始化根日志器。重复调用时保持幂等。"""
    global _LOGGING_READY
    if _LOGGING_READY:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(TraceContextFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
    _LOGGING_READY = True


def get_logger(name: str) -> logging.Logger:
    """获取具名日志器。"""
    return logging.getLogger(name)
