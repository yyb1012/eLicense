# Time: 2026-04-18 19:53
# Description: 实现基于 trace_id 的重放流程，并对关键字段执行一致性比对。
# Author: Feixue

from __future__ import annotations

from typing import Any

from harness.replay.trace_store import TRACE_REPLAY_STORE
from src.agent.graph.builder import Orchestrator


async def replay_trace(
    trace_id: str,
    *,
    orchestrator: Orchestrator | None = None,
) -> dict[str, Any]:
    """按 trace_id 重放一次执行，并输出关键字段比对结果。"""
    record = TRACE_REPLAY_STORE.get(trace_id)
    orchestrator = orchestrator or Orchestrator()

    replay_state = dict(record.state_input)
    replay_output = await orchestrator.run(replay_state)

    original_snapshot = _extract_snapshot(record.output)
    replay_snapshot = _extract_snapshot(replay_output)
    comparisons = {
        key: {
            "original": original_snapshot[key],
            "replayed": replay_snapshot[key],
            "matched": original_snapshot[key] == replay_snapshot[key],
        }
        for key in original_snapshot
    }
    all_matched = all(item["matched"] for item in comparisons.values())

    return {
        "trace_id": trace_id,
        "scenario_id": record.scenario_id,
        "comparisons": comparisons,
        "all_matched": all_matched,
        "replay_output": replay_output,
    }


def _extract_snapshot(output: dict[str, Any]) -> dict[str, Any]:
    """提取重放比对所需的关键字段，避免受无关字段波动影响。"""
    return {
        "route": str(output.get("route", "human_review")),
        "decision": str(output.get("decision_final", {}).get("action", "human_review")),
        "risk_level": str(output.get("risk_report", {}).get("risk_level", "unknown")),
        "writeback_status": str(output.get("writeback_result", {}).get("status", "not_executed")),
    }
