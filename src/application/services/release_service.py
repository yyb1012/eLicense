# Time: 2026-04-18 21:16
# Description: 编排灰度发布与回滚演练流程，聚合评测门禁和巡检信号并输出可审计报告。
# Author: Feixue

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from harness.eval.evaluator import evaluate_runs
from harness.eval.scenario_runner import run_scenario_batch
from harness.gates.release_gate import evaluate_release_gate
from harness.gates.rollout_gate import RolloutGateThresholds, evaluate_rollout_stage_gate
from harness.scenarios.scenario_loader import load_scenarios
from src.application.services.inspection_service import InspectionService
from src.ops.inspection.rule_checker import InspectionThresholds
from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


class ReleaseService:
    """N16 发布与回滚演练服务。

    职责边界：
    1. 负责编排灰度放量（5% -> 20% -> 50% -> 100%）和阶段门禁。
    2. 负责在阻断条件下执行“回滚演练占位动作”，输出可审计报告。
    3. 不执行真实部署与真实基础设施回退，仅产出可验证的流程证据。
    """

    _ROLLOUT_STRATEGY = [5, 20, 50, 100]
    _STAGE_STATUSES = ("pending", "running", "passed", "blocked", "rolled_back")

    def __init__(self, *, inspection_service: InspectionService) -> None:
        settings = get_settings()
        self._inspection_service = inspection_service
        self._release_reports: list[dict[str, Any]] = []
        self._rollback_reports: list[dict[str, Any]] = []
        self._release_seq = 0
        self._rollback_seq = 0

        # 本运行时开关用于回滚演练动作记录，不直接改写环境变量。
        self._runtime_feature_enable_writeback = bool(settings.feature_enable_writeback)
        self._current_version = "v0.1.0-rc"
        self._last_stable_version = "v0.0.9-stable"

    async def run_release_drill(
        self,
        *,
        trace_id: str,
        eval_metrics_override: dict[str, float] | None = None,
        inspection_metrics_override: dict[str, Any] | None = None,
        consecutive_abnormal_alerts_override: int | None = None,
    ) -> dict[str, Any]:
        """执行一次灰度发布与回滚演练。

        参数说明：
        - eval_metrics_override: 覆盖 Eval 指标，便于门禁演练。
        - inspection_metrics_override:
          1. 传平铺字典时，对所有阶段生效。
          2. 传 {"quick": {...}, "deep": {...}} 时，按巡检模式生效。
        - consecutive_abnormal_alerts_override: 强制覆盖连续告警次数，便于回滚条件演练。
        """
        release_id = self._next_release_id()
        stage_reports = [
            self._new_stage_report(trace_id=trace_id, index=index, traffic_percent=traffic)
            for index, traffic in enumerate(self._ROLLOUT_STRATEGY, start=1)
        ]

        eval_report = await self._build_eval_report(eval_metrics_override or {})
        eval_gate_result = evaluate_release_gate(eval_report)

        latest_passed_stage_index = -1
        blocked_stage_index: int | None = None
        latest_inspection_report: dict[str, Any] = {}
        latest_consecutive_abnormal_alerts = 0

        for idx, stage in enumerate(stage_reports):
            stage["status"] = "running"
            stage["started_at_utc"] = _utc_now()

            inspection_mode = self._inspection_mode_for_traffic(stage["traffic_percent"])
            metrics_override_for_stage = self._resolve_inspection_override(
                raw_override=inspection_metrics_override or {},
                mode=inspection_mode,
            )
            inspection_report = await self._inspection_service.run_inspection(
                mode=inspection_mode,
                trigger="release_gate",
                trace_id=f"{trace_id}-release-{stage['traffic_percent']}",
                metrics_override=metrics_override_for_stage,
            )
            latest_inspection_report = inspection_report

            consecutive_abnormal_alerts = self._count_consecutive_abnormal_alerts()
            if consecutive_abnormal_alerts_override is not None:
                consecutive_abnormal_alerts = max(int(consecutive_abnormal_alerts_override), 0)
            latest_consecutive_abnormal_alerts = consecutive_abnormal_alerts

            stage_gate_result = evaluate_rollout_stage_gate(
                eval_gate_result=eval_gate_result,
                latest_inspection_report=inspection_report,
                consecutive_abnormal_alerts=consecutive_abnormal_alerts,
                thresholds=RolloutGateThresholds(),
            )

            stage["gate_result"] = stage_gate_result
            stage["inspection_report_ref"] = inspection_report.get("report_id")
            stage["blocking_reasons"] = list(stage_gate_result.get("blocking_reasons", []))
            stage["finished_at_utc"] = _utc_now()

            if stage_gate_result.get("overall_passed", False):
                stage["status"] = "passed"
                latest_passed_stage_index = idx
                continue

            stage["status"] = "blocked"
            blocked_stage_index = idx
            break

        rollback_report: dict[str, Any] | None = None
        overall_status = "passed" if blocked_stage_index is None else "blocked"
        rollback_ref: str | None = None

        if blocked_stage_index is not None:
            rollback_report = self._run_rollback_drill(
                trace_id=trace_id,
                release_id=release_id,
                blocked_stage=stage_reports[blocked_stage_index],
                eval_gate_result=eval_gate_result,
                latest_inspection_report=latest_inspection_report,
                consecutive_abnormal_alerts=latest_consecutive_abnormal_alerts,
            )
            if rollback_report.get("executed", False):
                rollback_ref = rollback_report["rollback_id"]
                overall_status = "rolled_back"

                # 回滚执行后，将已通过阶段标记为 rolled_back，保持阶段状态可追溯。
                for stage in stage_reports:
                    if stage.get("status") == "passed":
                        stage["status"] = "rolled_back"

                self._rollback_reports.append(rollback_report)

        release_report = {
            "release_id": release_id,
            "trace_id": trace_id,
            "rollout_strategy": list(self._ROLLOUT_STRATEGY),
            "stage_statuses": list(self._STAGE_STATUSES),
            "stages": stage_reports,
            "overall_status": overall_status,
            "eval_report_metrics": dict(eval_report.get("metrics", {})),
            "eval_gate_result": eval_gate_result,
            "rollback_ref": rollback_ref,
            "created_at_utc": _utc_now(),
        }

        self._release_reports.append(release_report)
        logger.info(
            "release_drill_completed",
            extra={
                "extra_fields": {
                    "release_id": release_id,
                    "trace_id": trace_id,
                    "overall_status": overall_status,
                    "rollback_ref": rollback_ref,
                }
            },
        )

        if rollback_report is not None:
            release_report["rollback_report"] = rollback_report
        return release_report

    def list_release_reports(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """查询发布演练报告列表。"""
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self._release_reports[-safe_limit:]))

    def list_rollback_reports(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """查询回滚演练报告列表。"""
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self._rollback_reports[-safe_limit:]))

    async def _build_eval_report(self, eval_metrics_override: dict[str, float]) -> dict[str, Any]:
        """执行 Scenario + Eval，并支持指标覆盖注入用于门禁演练。"""
        scenarios = load_scenarios()
        run_results = await run_scenario_batch(scenarios)
        eval_report = evaluate_runs(run_results)

        if eval_metrics_override:
            metrics = dict(eval_report.get("metrics", {}))
            for key, value in eval_metrics_override.items():
                metrics[str(key)] = _as_float(value)
            eval_report["metrics"] = metrics
            eval_report["override_applied"] = True
        return eval_report

    def _run_rollback_drill(
        self,
        *,
        trace_id: str,
        release_id: str,
        blocked_stage: dict[str, Any],
        eval_gate_result: dict[str, Any],
        latest_inspection_report: dict[str, Any],
        consecutive_abnormal_alerts: int,
    ) -> dict[str, Any]:
        """执行回滚演练占位流程。

        触发条件按主文档定义：
        1. 决策准确率跌破阈值
        2. 写回失败率超阈值
        3. 巡检连续告警
        """
        triggers = self._detect_rollback_triggers(
            eval_gate_result=eval_gate_result,
            latest_inspection_report=latest_inspection_report,
            consecutive_abnormal_alerts=consecutive_abnormal_alerts,
        )

        rollback_id = self._next_rollback_id()
        if not triggers:
            return {
                "rollback_id": rollback_id,
                "trace_id": trace_id,
                "release_ref": release_id,
                "executed": False,
                "result": "skipped_no_trigger",
                "trigger_reasons": [],
                "blocked_stage": {
                    "stage_id": blocked_stage.get("stage_id"),
                    "traffic_percent": blocked_stage.get("traffic_percent"),
                },
                "steps": [],
                "manual_confirmation_points": [],
                "created_at_utc": _utc_now(),
            }

        action_steps = [
            {
                "order": 1,
                "step": "disable_writeback_feature",
                "detail": "将运行时写回开关置为 false（演练占位，不改环境变量）。",
                "status": "done",
                "requires_human_confirmation": False,
            },
            {
                "order": 2,
                "step": "rollback_to_last_stable_version",
                "detail": f"回退到上一个稳定版本 {self._last_stable_version}（演练占位，不执行真实部署回退）。",
                "status": "done",
                "requires_human_confirmation": True,
            },
            {
                "order": 3,
                "step": "record_incident_review_entry",
                "detail": "记录事件复盘入口并要求值班人员确认后续处置。",
                "status": "done",
                "requires_human_confirmation": True,
            },
        ]

        # 第一步：关闭写回开关（运行时标记），对应主文档回滚动作顺序 1。
        self._runtime_feature_enable_writeback = False
        # 第二步：记录当前版本已回退（占位），对应顺序 2。
        self._current_version = self._last_stable_version

        manual_confirmation_points = [
            item["step"] for item in action_steps if item["requires_human_confirmation"]
        ]

        return {
            "rollback_id": rollback_id,
            "trace_id": trace_id,
            "release_ref": release_id,
            "executed": True,
            "result": "success_stub",
            "trigger_reasons": triggers,
            "blocked_stage": {
                "stage_id": blocked_stage.get("stage_id"),
                "traffic_percent": blocked_stage.get("traffic_percent"),
            },
            "steps": action_steps,
            "manual_confirmation_points": manual_confirmation_points,
            "runtime_feature_enable_writeback": self._runtime_feature_enable_writeback,
            "current_version": self._current_version,
            "created_at_utc": _utc_now(),
        }

    def _detect_rollback_triggers(
        self,
        *,
        eval_gate_result: dict[str, Any],
        latest_inspection_report: dict[str, Any],
        consecutive_abnormal_alerts: int,
    ) -> list[str]:
        """按主文档定义识别回滚触发条件。"""
        triggers: list[str] = []

        decision_accuracy_check = eval_gate_result.get("checks", {}).get("decision_accuracy", {})
        if not bool(decision_accuracy_check.get("passed", False)):
            triggers.append("decision_accuracy_below_threshold")

        writeback_failure_rate = _as_float(
            latest_inspection_report.get("metrics", {}).get("writeback_failure_rate", 0.0)
        )
        if writeback_failure_rate > InspectionThresholds().writeback_failure_rate_max:
            triggers.append("writeback_failure_rate_exceeded")

        if int(consecutive_abnormal_alerts) > RolloutGateThresholds().consecutive_abnormal_alerts_max:
            triggers.append("consecutive_inspection_alerts")

        return triggers

    def _count_consecutive_abnormal_alerts(self) -> int:
        """统计最新连续 abnormal 巡检次数，用于发布阻断与回滚触发。"""
        count = 0
        for report in self._inspection_service.list_reports(limit=50):
            if str(report.get("status", "normal")) != "abnormal":
                break
            count += 1
        return count

    def _inspection_mode_for_traffic(self, traffic_percent: int) -> str:
        """按放量阶段选择巡检模式：高流量阶段使用 deep 巡检。"""
        return "deep" if traffic_percent >= 50 else "quick"

    def _resolve_inspection_override(
        self,
        *,
        raw_override: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        """解析巡检指标覆盖配置。

        支持两种配置方式：
        1. 平铺：{"request_error_rate": 0.2}
        2. 分模式：{"quick": {...}, "deep": {...}}
        """
        if not isinstance(raw_override, dict):
            return {}

        mode_payload = raw_override.get(mode)
        if isinstance(mode_payload, dict):
            return dict(mode_payload)

        return {
            key: value
            for key, value in raw_override.items()
            if not isinstance(value, dict)
        }

    def _new_stage_report(self, *, trace_id: str, index: int, traffic_percent: int) -> dict[str, Any]:
        """创建阶段报告骨架，未执行前默认为 pending。"""
        return {
            "stage_id": f"STAGE-{index:02d}",
            "trace_id": trace_id,
            "traffic_percent": traffic_percent,
            "status": "pending",
            "gate_result": None,
            "blocking_reasons": [],
            "inspection_report_ref": None,
            "started_at_utc": None,
            "finished_at_utc": None,
        }

    def _next_release_id(self) -> str:
        """生成发布演练编号。"""
        self._release_seq += 1
        return f"REL-{self._release_seq:06d}"

    def _next_rollback_id(self) -> str:
        """生成回滚演练编号。"""
        self._rollback_seq += 1
        return f"RBK-{self._rollback_seq:06d}"


def _utc_now() -> str:
    """生成 UTC 时间戳。"""
    return datetime.now(tz=timezone.utc).isoformat()


def _as_float(value: Any) -> float:
    """安全转换为浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
