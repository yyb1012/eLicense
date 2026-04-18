# Time: 2026-04-18 20:53
# Description: 校验巡检规则检查在正常与异常输入下的判定稳定性与结构完整性。
# Author: Feixue

from __future__ import annotations

from src.ops.inspection.rule_checker import evaluate_metrics_rules


def test_rule_checker_returns_normal_for_healthy_metrics() -> None:
    """健康指标应全部通过并返回 normal。"""
    metrics = {
        "request_error_rate": 0.01,
        "latency_p95_ms": 300,
        "latency_p99_ms": 600,
        "tool_failure_rate": 0.01,
        "empty_recall_rate": 0.005,
        "writeback_failure_rate": 0.005,
        "compensation_trigger_count": 0,
        "human_review_ratio": 0.1,
    }

    result = evaluate_metrics_rules(metrics)

    assert result["status"] == "normal"
    assert result["triggered_rules"] == []
    assert result["summary"]["failed_count"] == 0
    assert all(item["passed"] is True for item in result["checks"].values())


def test_rule_checker_returns_abnormal_when_threshold_exceeded() -> None:
    """任一指标超过阈值时必须返回 abnormal，并列出触发规则。"""
    metrics = {
        "request_error_rate": 0.20,
        "latency_p95_ms": 7000,
        "latency_p99_ms": 9500,
        "tool_failure_rate": 0.12,
        "empty_recall_rate": 0.06,
        "writeback_failure_rate": 0.08,
        "compensation_trigger_count": 6,
        "human_review_ratio": 0.6,
    }

    result = evaluate_metrics_rules(metrics)

    assert result["status"] == "abnormal"
    assert result["summary"]["failed_count"] >= 1
    assert "request_error_rate" in result["triggered_rules"]
    assert result["checks"]["request_error_rate"]["passed"] is False
    assert result["checks"]["latency_p95_ms"]["passed"] is False
