from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

_TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    return uuid4().hex


def bind_trace_id(trace_id: str) -> None:
    _TRACE_ID.set(trace_id)


def get_trace_id() -> str | None:
    return _TRACE_ID.get()


def ensure_trace_id() -> str:
    trace_id = get_trace_id()
    if trace_id:
        return trace_id
    trace_id = new_trace_id()
    bind_trace_id(trace_id)
    return trace_id


def clear_trace_id() -> None:
    _TRACE_ID.set(None)
