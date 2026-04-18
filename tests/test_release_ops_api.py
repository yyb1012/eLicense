# Time: 2026-04-18 21:22
# Description: 校验发布演练 API 的触发与报告查询契约，确保 trace_id 与结构化输出稳定。
# Author: Feixue

from __future__ import annotations


def test_ops_release_drill_run_endpoint_contract(client) -> None:
    """POST /api/v1/ops/release/drill/run 应返回发布演练报告。"""
    response = client.post(
        "/api/v1/ops/release/drill/run",
        json={
            "eval_metrics_override": {
                "decision_accuracy": 0.99,
                "evidence_consistency": 0.99,
                "rejection_reasonableness": 0.99,
                "p95_latency_s": 0.3,
                "degrade_success_rate": 0.99,
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["trace_id"], str)
    assert body["release_report"]["release_id"].startswith("REL-")
    assert len(body["release_report"]["stages"]) == 4
    assert response.headers["x-trace-id"] == body["trace_id"]


def test_ops_release_reports_endpoint_contract(client) -> None:
    """GET /api/v1/ops/release/reports 应返回发布演练记录。"""
    client.post(
        "/api/v1/ops/release/drill/run",
        json={
            "eval_metrics_override": {
                "decision_accuracy": 0.99,
                "evidence_consistency": 0.99,
                "rejection_reasonableness": 0.99,
                "p95_latency_s": 0.3,
                "degrade_success_rate": 0.99,
            }
        },
    )
    response = client.get("/api/v1/ops/release/reports")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["reports"], list)
    assert len(body["reports"]) >= 1
    assert "release_id" in body["reports"][0]


def test_ops_rollback_reports_endpoint_contract(client) -> None:
    """GET /api/v1/ops/release/rollbacks 在阻断演练后应返回回滚记录。"""
    client.post(
        "/api/v1/ops/release/drill/run",
        json={
            "eval_metrics_override": {
                "decision_accuracy": 0.1,
                "evidence_consistency": 0.99,
                "rejection_reasonableness": 0.99,
                "p95_latency_s": 0.3,
                "degrade_success_rate": 0.99,
            }
        },
    )
    response = client.get("/api/v1/ops/release/rollbacks")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["rollbacks"], list)
    assert len(body["rollbacks"]) >= 1
    assert "rollback_id" in body["rollbacks"][0]
    assert "trigger_reasons" in body["rollbacks"][0]
