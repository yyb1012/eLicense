# Time: 2026-04-18 19:53
# Description: 提供基于 trace_id 的执行记录存储，用于 Replay Harness 重放与比对。
# Author: Feixue

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TraceRecord:
    """保存一次执行的输入快照、输出快照与耗时。"""

    trace_id: str
    state_input: dict[str, Any]
    output: dict[str, Any]
    latency_ms: float
    scenario_id: str
    recorded_at_utc: str


class TraceReplayStore:
    """内存级 trace 存储，满足本地测试与最小 Harness 回放需求。"""

    def __init__(self) -> None:
        self._records: dict[str, TraceRecord] = {}

    def save(
        self,
        *,
        trace_id: str,
        state_input: dict[str, Any],
        output: dict[str, Any],
        latency_ms: float,
        scenario_id: str,
    ) -> TraceRecord:
        """按 trace_id 保存执行记录；同 key 再写入会覆盖为最新快照。"""
        record = TraceRecord(
            trace_id=trace_id,
            state_input=dict(state_input),
            output=dict(output),
            latency_ms=float(latency_ms),
            scenario_id=scenario_id,
            recorded_at_utc=datetime.now(tz=timezone.utc).isoformat(),
        )
        self._records[trace_id] = record
        return record

    def get(self, trace_id: str) -> TraceRecord:
        """读取指定 trace 记录，不存在时抛出 KeyError。"""
        return self._records[trace_id]

    def clear(self) -> None:
        """清空存储，避免跨测试污染。"""
        self._records.clear()


TRACE_REPLAY_STORE = TraceReplayStore()
