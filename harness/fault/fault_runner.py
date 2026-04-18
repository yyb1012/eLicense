# Time: 2026-04-18 19:55
# Description: 执行最小故障注入场景，验证单路/双路检索故障及写回补偿行为。
# Author: Feixue

from __future__ import annotations

from typing import Any

from src.agent.graph.builder import Orchestrator


async def run_fault_case(
    fault_type: str,
    *,
    orchestrator: Orchestrator | None = None,
) -> dict[str, Any]:
    """按故障类型执行一次主链路，并输出断言与审计关键信息。"""
    orchestrator = orchestrator or Orchestrator()
    state = _build_fault_state(fault_type)

    output = await orchestrator.run(state)
    route = str(output.get("route", "human_review"))
    writeback_status = str(output.get("writeback_result", {}).get("status", "not_executed"))

    expected = _expected_outcome(fault_type)
    checks = {
        "route_expected": route == expected["route"],
        "audit_present": bool(output.get("audit_report", {}).get("version")),
        "writeback_status_expected": writeback_status == expected["writeback_status"],
    }

    return {
        "fault_type": fault_type,
        "checks": checks,
        "all_passed": all(checks.values()),
        "route": route,
        "writeback_status": writeback_status,
        "errors": list(output.get("errors", [])),
        "blocking_signals": list(output.get("quality_report", {}).get("blocking_signals", [])),
        "output": output,
    }


def _build_fault_state(fault_type: str) -> dict[str, Any]:
    """构造故障注入输入状态，确保每类故障的触发条件可复现。"""
    base_state = {
        "trace_id": f"fault-{fault_type}",
        "session_id": "S-FAULT-001",
        "work_order_id": "WO-FAULT-001",
        "user_input": "营业执照初审核验企业名称一致性",
        "feature_enable_writeback": False,
        "max_analysis_attempts": 2,
        "fault_injection": {},
    }

    if fault_type == "retrieval_single_path_failure":
        base_state["fault_injection"] = {"simulate_fail_fts": True}
    elif fault_type == "retrieval_dual_path_failure":
        base_state["fault_injection"] = {
            "simulate_fail_fts": True,
            "simulate_fail_vector": True,
        }
        # 双路故障场景下将预算设置为 1，避免回边后引入额外不确定性。
        base_state["max_analysis_attempts"] = 1
    elif fault_type == "writeback_failure":
        base_state["feature_enable_writeback"] = True
        base_state["fault_injection"] = {"writeback_fail": True}
    else:
        raise ValueError(f"unsupported fault_type: {fault_type}")

    return base_state


def _expected_outcome(fault_type: str) -> dict[str, str]:
    """定义每类故障的期望输出，便于统一断言。"""
    mapping = {
        "retrieval_single_path_failure": {
            "route": "degrade",
            "writeback_status": "not_executed",
        },
        "retrieval_dual_path_failure": {
            "route": "human_review",
            "writeback_status": "not_executed",
        },
        "writeback_failure": {
            "route": "pass",
            "writeback_status": "compensated_stub",
        },
    }
    return mapping[fault_type]
