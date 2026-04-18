# Time: 2026-04-18 19:56
# Description: 负责在 pass 路由下执行写回占位流程，并支持故障注入触发补偿分支。
# Author: Feixue

from __future__ import annotations

from src.agent.graph.state import GraphState
from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


async def run_writeback_subgraph(state: GraphState) -> GraphState:
    """执行 N10：WriteBack 幂等占位、开关判断与补偿信号输出。"""
    route = str(state.get("route", "human_review"))
    idempotency_key = _build_idempotency_key(state)
    writeback_enabled = _resolve_writeback_enabled(state)

    # 编排层应只在 pass 路由进入本节点；此处保留兜底避免误调用造成副作用。
    if route != "pass":
        writeback_result = {
            "version": "n10-writeback-v1",
            "status": "skipped_non_pass_route",
            "code": "WRITEBACK_SKIPPED_NON_PASS_ROUTE",
            "idempotency_key": idempotency_key,
            "compensated": False,
            "detail": "writeback node called on non-pass route",
        }
        logger.info(
            "writeback_skipped_non_pass_route",
            extra={"extra_fields": {"route": route, "idempotency_key": idempotency_key}},
        )
        return {"writeback_result": writeback_result}

    if not writeback_enabled:
        writeback_result = {
            "version": "n10-writeback-v1",
            "status": "skipped_disabled",
            "code": "WRITEBACK_DISABLED",
            "idempotency_key": idempotency_key,
            "compensated": False,
            "detail": "feature flag disabled",
        }
        logger.info(
            "writeback_skipped_feature_disabled",
            extra={"extra_fields": {"idempotency_key": idempotency_key}},
        )
        return {"writeback_result": writeback_result}

    try:
        _simulate_writeback_side_effect(state)
    except Exception as exc:  # pragma: no cover - branch covered via integration behavior
        writeback_result = {
            "version": "n10-writeback-v1",
            "status": "compensated_stub",
            "code": "WRITEBACK_COMPENSATED",
            "idempotency_key": idempotency_key,
            "compensated": True,
            "detail": str(exc),
        }
        errors = _append_unique_error(state.get("errors", []), "writeback_compensated")
        logger.warning(
            "writeback_compensated",
            extra={"extra_fields": {"idempotency_key": idempotency_key, "reason": str(exc)}},
        )
        return {"writeback_result": writeback_result, "errors": errors}

    writeback_result = {
        "version": "n10-writeback-v1",
        "status": "succeeded_stub",
        "code": "WRITEBACK_STUB_OK",
        "idempotency_key": idempotency_key,
        "compensated": False,
        "detail": "no real external side effect in current stage",
    }
    logger.info(
        "writeback_succeeded_stub",
        extra={"extra_fields": {"idempotency_key": idempotency_key}},
    )
    return {"writeback_result": writeback_result}


def _build_idempotency_key(state: GraphState) -> str:
    """使用 trace_id/work_order_id 生成写回幂等键。"""
    trace_id = str(state.get("trace_id", "-")).strip() or "-"
    work_order_id = str(state.get("work_order_id", "-")).strip() or "-"
    return f"{trace_id}:{work_order_id}"


def _resolve_writeback_enabled(state: GraphState) -> bool:
    """优先读取状态显式开关，其次回退到配置。"""
    if "feature_enable_writeback" in state:
        return bool(state.get("feature_enable_writeback"))
    return bool(get_settings().feature_enable_writeback)


def _simulate_writeback_side_effect(state: GraphState) -> None:
    """写回占位执行器：仅用于流程联调，不执行真实外部副作用。"""
    fault_injection = state.get("fault_injection", {})
    if isinstance(fault_injection, dict) and bool(fault_injection.get("writeback_fail", False)):
        raise RuntimeError("forced_writeback_failure")
    if bool(state.get("force_writeback_failure", False)):
        raise RuntimeError("forced_writeback_failure")


def _append_unique_error(raw_errors: object, code: str) -> list[str]:
    """追加错误码并保持顺序稳定，避免重复堆叠同类错误。"""
    errors = [str(item) for item in raw_errors] if isinstance(raw_errors, list) else []
    if code not in errors:
        errors.append(code)
    return errors
