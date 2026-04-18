# Time: 2026-04-18 15:50
# Description: 管理请求级 trace_id 的上下文读写与生成。
# Author: Feixue

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

# 每个协程上下文独立维护 trace_id，避免并发请求互相污染。
_TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    """生成新的 trace_id。"""
    return uuid4().hex


def bind_trace_id(trace_id: str) -> None:
    """将 trace_id 绑定到当前上下文。"""
    _TRACE_ID.set(trace_id)


def get_trace_id() -> str | None:
    """读取当前上下文中的 trace_id。"""
    return _TRACE_ID.get()


def ensure_trace_id() -> str:
    """保证返回可用 trace_id；不存在时自动创建并绑定。"""
    trace_id = get_trace_id()
    if trace_id:
        return trace_id
    trace_id = new_trace_id()
    bind_trace_id(trace_id)
    return trace_id


def clear_trace_id() -> None:
    """清理当前上下文中的 trace_id。"""
    _TRACE_ID.set(None)
