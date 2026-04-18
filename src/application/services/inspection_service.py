# Time: 2026-04-18 20:51
# Description: 编排规则巡检与异常归因流程，提供报告与事件台账的内存化管理能力。
# Author: Feixue

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.ops.inspection.agent_inspector import inspect_abnormal_report
from src.ops.inspection.alert_dispatcher import dispatch_alert_event
from src.ops.inspection.rule_checker import evaluate_metrics_rules
from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


class InspectionService:
    """巡检应用服务。

    职责边界：
    1. 负责拉起一次巡检闭环：MetricsCollector -> RuleChecker -> (AgentInspector) -> Alert -> Incident。
    2. 负责报告和事件的内存存储，满足当前阶段本地可运行、可测试、可追溯要求。
    3. 不负责真实外部告警平台与分布式调度集成。
    """

    def __init__(self, *, feature_enable_inspection_agent: bool | None = None) -> None:
        settings = get_settings()
        if feature_enable_inspection_agent is None:
            feature_enable_inspection_agent = settings.feature_enable_inspection_agent

        self._feature_enable_inspection_agent = bool(feature_enable_inspection_agent)
        self._reports: list[dict[str, Any]] = []
        self._incidents: list[dict[str, Any]] = []
        self._report_seq = 0
        self._incident_seq = 0

    async def run_inspection(
        self,
        *,
        mode: str,
        trigger: str,
        trace_id: str,
        metrics_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一次巡检并产出结构化报告。

        参数说明：
        - mode: quick/deep，用于表示巡检粒度。
        - trigger: manual/scheduler，用于区分触发来源。
        - trace_id: 全链路追踪 ID，要求在 API 层和日志层一致。
        - metrics_override: 测试与演练注入指标覆盖值，不依赖真实监控系统。
        """
        normalized_mode = mode if mode in {"quick", "deep"} else "quick"
        normalized_trigger = trigger if trigger in {"manual", "scheduler"} else "manual"

        metrics = self._collect_metrics(
            mode=normalized_mode,
            metrics_override=metrics_override or {},
        )
        rule_result = evaluate_metrics_rules(metrics)

        report_id = self._next_report_id()
        status = str(rule_result["status"])
        agent_inspection = self._default_agent_payload(status=status)
        alert_event: dict[str, Any] | None = None
        incident_ref: str | None = None

        # 只有 abnormal 才触发后续告警与事件记录，避免告警噪音。
        if status == "abnormal":
            if self._feature_enable_inspection_agent:
                agent_result = inspect_abnormal_report(
                    {
                        "report_id": report_id,
                        "trace_id": trace_id,
                        "mode": normalized_mode,
                        "metrics": metrics,
                        "rule_result": rule_result,
                    }
                )
                agent_inspection = {
                    "executed": True,
                    "skipped": False,
                    **agent_result,
                }
            else:
                # 开关关闭时仍要保留可观测信号，避免误解为“链路未执行”。
                agent_inspection = {
                    "executed": False,
                    "skipped": True,
                    "reason": "feature_enable_inspection_agent_disabled",
                    "possible_causes": [],
                    "impact_scope": {
                        "inspection_mode": normalized_mode,
                        "affected_metrics": list(rule_result.get("triggered_rules", [])),
                        "estimated_user_impact": "agent inspector disabled",
                        "requires_manual_confirmation": True,
                    },
                    "recommended_actions": [],
                    "confidence": 0.0,
                    "constraints": {
                        "auto_execute_allowed": False,
                        "high_risk_requires_human_confirmation": True,
                    },
                }

            alert_event = dispatch_alert_event(
                report_id=report_id,
                trace_id=trace_id,
                mode=normalized_mode,
                triggered_rules=list(rule_result.get("triggered_rules", [])),
            )
            incident = self._append_incident(
                report_id=report_id,
                trace_id=trace_id,
                mode=normalized_mode,
                rule_result=rule_result,
                agent_inspection=agent_inspection,
                alert_event=alert_event,
            )
            incident_ref = incident["incident_id"]

        report = {
            "report_id": report_id,
            "trace_id": trace_id,
            "mode": normalized_mode,
            "trigger": normalized_trigger,
            "status": status,
            "metrics": metrics,
            "rule_result": rule_result,
            "agent_inspection": agent_inspection,
            "alert_event": alert_event,
            "incident_ref": incident_ref,
            "created_at_utc": _utc_now(),
        }
        self._reports.append(report)

        logger.info(
            "inspection_report_generated",
            extra={
                "extra_fields": {
                    "report_id": report_id,
                    "trace_id": trace_id,
                    "status": status,
                    "mode": normalized_mode,
                    "triggered_rules": rule_result.get("triggered_rules", []),
                    "incident_ref": incident_ref,
                }
            },
        )
        return report

    def list_reports(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """查询巡检报告列表（按时间倒序）。"""
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self._reports[-safe_limit:]))

    def list_incidents(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """查询异常事件列表（按时间倒序）。"""
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self._incidents[-safe_limit:]))

    def build_daily_summary(self) -> dict[str, Any]:
        """构建日报汇总占位输出。

        当前阶段只聚合本进程内数据，后续可扩展为落库和报表任务。
        """
        abnormal_count = sum(1 for item in self._reports if item.get("status") == "abnormal")
        normal_count = len(self._reports) - abnormal_count
        return {
            "summary_id": f"SUM-{self._report_seq:06d}",
            "total_reports": len(self._reports),
            "normal_reports": normal_count,
            "abnormal_reports": abnormal_count,
            "total_incidents": len(self._incidents),
            "generated_at_utc": _utc_now(),
        }

    def _collect_metrics(
        self,
        *,
        mode: str,
        metrics_override: dict[str, Any],
    ) -> dict[str, Any]:
        """采集巡检指标（stub）。

        约束说明：
        1. 本阶段不接真实监控系统，使用稳定默认值 + override 机制。
        2. 指标字段固定，保证规则检查和测试断言口径一致。
        3. 深度巡检可使用与快速巡检不同的默认基线，便于后续策略扩展。
        """
        if mode == "deep":
            base_metrics = {
                "request_error_rate": 0.012,
                "latency_p95_ms": 680.0,
                "latency_p99_ms": 1200.0,
                "tool_failure_rate": 0.015,
                "empty_recall_rate": 0.008,
                "writeback_failure_rate": 0.006,
                "compensation_trigger_count": 0,
                "human_review_ratio": 0.12,
            }
        else:
            base_metrics = {
                "request_error_rate": 0.008,
                "latency_p95_ms": 420.0,
                "latency_p99_ms": 900.0,
                "tool_failure_rate": 0.010,
                "empty_recall_rate": 0.006,
                "writeback_failure_rate": 0.004,
                "compensation_trigger_count": 0,
                "human_review_ratio": 0.09,
            }

        # 允许通过 override 注入演练场景，便于 API 测试和故障演习。
        merged = {**base_metrics, **dict(metrics_override)}
        return {
            "request_error_rate": _as_float(merged.get("request_error_rate")),
            "latency_p95_ms": _as_float(merged.get("latency_p95_ms")),
            "latency_p99_ms": _as_float(merged.get("latency_p99_ms")),
            "tool_failure_rate": _as_float(merged.get("tool_failure_rate")),
            "empty_recall_rate": _as_float(merged.get("empty_recall_rate")),
            "writeback_failure_rate": _as_float(merged.get("writeback_failure_rate")),
            "compensation_trigger_count": _as_int(merged.get("compensation_trigger_count")),
            "human_review_ratio": _as_float(merged.get("human_review_ratio")),
        }

    def _default_agent_payload(self, *, status: str) -> dict[str, Any]:
        """构建默认 Agent 巡检输出，确保 normal 场景结构稳定。"""
        if status == "normal":
            return {
                "executed": False,
                "skipped": True,
                "reason": "inspection_status_normal",
                "possible_causes": [],
                "impact_scope": {
                    "inspection_mode": "unknown",
                    "affected_metrics": [],
                    "estimated_user_impact": "none",
                    "requires_manual_confirmation": True,
                },
                "recommended_actions": [],
                "confidence": 0.0,
                "constraints": {
                    "auto_execute_allowed": False,
                    "high_risk_requires_human_confirmation": True,
                },
            }
        return {
            "executed": False,
            "skipped": False,
            "possible_causes": [],
            "impact_scope": {},
            "recommended_actions": [],
            "confidence": 0.0,
            "constraints": {
                "auto_execute_allowed": False,
                "high_risk_requires_human_confirmation": True,
            },
        }

    def _append_incident(
        self,
        *,
        report_id: str,
        trace_id: str,
        mode: str,
        rule_result: dict[str, Any],
        agent_inspection: dict[str, Any],
        alert_event: dict[str, Any],
    ) -> dict[str, Any]:
        """记录异常事件台账，保留 report 与 alert 的关联引用。"""
        self._incident_seq += 1
        incident = {
            "incident_id": f"INC-{self._incident_seq:06d}",
            "report_ref": report_id,
            "trace_id": trace_id,
            "mode": mode,
            "triggered_rules": list(rule_result.get("triggered_rules", [])),
            "alert_ref": alert_event.get("alert_id"),
            "agent_confidence": float(agent_inspection.get("confidence", 0.0)),
            "status": "open",
            "created_at_utc": _utc_now(),
        }
        self._incidents.append(incident)
        return incident

    def _next_report_id(self) -> str:
        """生成巡检报告编号，保证单进程内唯一且可排序。"""
        self._report_seq += 1
        return f"RPT-{self._report_seq:06d}"


def _utc_now() -> str:
    """统一生成 UTC 时间戳，确保报告、事件与告警可串联。"""
    return datetime.now(tz=timezone.utc).isoformat()


def _as_float(value: Any) -> float:
    """将输入转为浮点数，解析失败时回退到 0.0。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    """将输入转为整数，解析失败时回退到 0。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
