from __future__ import annotations

from typing import TypedDict


class GraphState(TypedDict, total=False):
    trace_id: str
    session_id: str
    work_order_id: str
    user_input: str
    answer_text: str
    route: str
    errors: list[str]
