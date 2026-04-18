# Time: 2026-04-18 20:49
# Description: 在异常巡检结果上生成归因建议，强调人工确认边界并禁止自动高风险修复。
# Author: Feixue

from __future__ import annotations

from typing import Any


def inspect_abnormal_report(report: dict[str, Any]) -> dict[str, Any]:
    """根据异常巡检报告生成归因建议。

    约束：
    1. 本模块仅做“建议生成”，不执行任何修复动作。
    2. 高风险动作必须显式标记 requires_human_confirmation=True。
    3. 输出结构固定，便于后续日报、告警和事件复盘复用。
    """
    triggered_rules = list(report.get("rule_result", {}).get("triggered_rules", []))
    metrics = dict(report.get("metrics", {}))

    possible_causes: list[str] = []
    recommended_actions: list[dict[str, Any]] = []

    # 逐条异常规则映射到可解释根因，避免诊断“黑箱化”。
    for rule in triggered_rules:
        if rule == "request_error_rate":
            possible_causes.append("请求错误率升高，疑似下游依赖抖动或接口契约变更。")
            recommended_actions.append(
                _action(
                    action="排查最近 30 分钟错误日志并定位高频错误码",
                    risk_level="low",
                )
            )
        elif rule in {"latency_p95_ms", "latency_p99_ms"}:
            possible_causes.append("时延指标异常，疑似检索链路或外部调用耗时升高。")
            recommended_actions.append(
                _action(
                    action="检查检索与工具调用耗时分布，必要时启用降级路径",
                    risk_level="medium",
                )
            )
        elif rule == "tool_failure_rate":
            possible_causes.append("工具失败率偏高，疑似工具服务不稳定或超时配置不合理。")
            recommended_actions.append(
                _action(
                    action="切换到只读降级工具集并检查重试配置",
                    risk_level="medium",
                )
            )
        elif rule == "empty_recall_rate":
            possible_causes.append("空召回率升高，疑似检索过滤条件过严或索引质量下降。")
            recommended_actions.append(
                _action(
                    action="复查 Hard Filter 条件与索引同步状态",
                    risk_level="medium",
                )
            )
        elif rule in {"writeback_failure_rate", "compensation_trigger_count"}:
            possible_causes.append("写回链路异常，补偿触发频繁，存在副作用失败风险。")
            recommended_actions.append(
                _action(
                    action="暂停高风险写回并人工核对幂等键与补偿日志",
                    risk_level="high",
                )
            )
        elif rule == "human_review_ratio":
            possible_causes.append("人工复核比例异常升高，疑似质量门禁过严或证据质量下降。")
            recommended_actions.append(
                _action(
                    action="抽样复核 quality_gate 阻断信号并评估阈值是否偏紧",
                    risk_level="medium",
                )
            )

    # 若没有命中具体规则，给出保守兜底建议，保证输出字段完整。
    if not possible_causes:
        possible_causes.append("未识别到明确根因，建议结合 trace 与回放结果做人工排查。")
        recommended_actions.append(
            _action(action="执行 trace_id 回放并人工比对关键字段", risk_level="low")
        )

    impact_scope = {
        "inspection_mode": str(report.get("mode", "unknown")),
        "affected_metrics": triggered_rules,
        "estimated_user_impact": _estimate_user_impact(metrics=metrics, triggered_rules=triggered_rules),
        "requires_manual_confirmation": True,
    }

    confidence = _estimate_confidence(triggered_rules)
    return {
        "possible_causes": possible_causes,
        "impact_scope": impact_scope,
        "recommended_actions": recommended_actions,
        "confidence": confidence,
        "constraints": {
            "auto_execute_allowed": False,
            "high_risk_requires_human_confirmation": True,
        },
    }


def _action(*, action: str, risk_level: str) -> dict[str, Any]:
    """构造行动建议并显式标注人工确认边界。"""
    return {
        "action": action,
        "risk_level": risk_level,
        "requires_human_confirmation": risk_level in {"high", "critical"},
    }


def _estimate_user_impact(*, metrics: dict[str, Any], triggered_rules: list[str]) -> str:
    """基于异常规则估算影响范围，提供值班可读的影响摘要。"""
    if "request_error_rate" in triggered_rules:
        return "可能影响多数在线请求，需优先处理。"
    if "writeback_failure_rate" in triggered_rules or "compensation_trigger_count" in triggered_rules:
        return "主要影响写回路径，需人工核对副作用一致性。"
    if "human_review_ratio" in triggered_rules:
        return "主要影响处理效率，人工复核压力上升。"
    if float(metrics.get("latency_p99_ms", 0.0)) > 9000:
        return "高峰期用户响应延迟明显增加。"
    return "影响范围有限，建议继续观察并保持告警跟踪。"


def _estimate_confidence(triggered_rules: list[str]) -> float:
    """根据触发规则数量估算置信度，规则越多说明异常信号越一致。"""
    if not triggered_rules:
        return 0.45
    score = 0.55 + (0.08 * len(triggered_rules))
    return round(min(score, 0.92), 2)
