# Time: 2026-04-18 20:53
# Description: 校验 Ops API 三个接口的契约稳定性与 trace_id 回传行为。
# Author: Feixue

from __future__ import annotations


def test_ops_run_inspection_endpoint_contract(client) -> None:
    """POST /api/v1/ops/inspection/run 应返回 report 与 trace_id。"""
    response = client.post(
        "/api/v1/ops/inspection/run",
        json={"mode": "quick"},
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
    assert body["report"]["report_id"].startswith("RPT-")
    assert body["report"]["status"] in {"normal", "abnormal"}
    assert response.headers["x-trace-id"] == body["trace_id"]


def test_ops_reports_endpoint_contract(client) -> None:
    """GET /api/v1/ops/inspection/reports 应返回报告列表。"""
    client.post("/api/v1/ops/inspection/run", json={"mode": "quick"})
    response = client.get("/api/v1/ops/inspection/reports")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["trace_id"], str)
    assert isinstance(body["reports"], list)
    assert len(body["reports"]) >= 1
    assert "report_id" in body["reports"][0]
    assert "status" in body["reports"][0]


def test_ops_incidents_endpoint_contract(client) -> None:
    """GET /api/v1/ops/incidents 在异常巡检后应返回 incident 列表。"""
    client.post(
        "/api/v1/ops/inspection/run",
        json={
            "mode": "quick",
            "metrics_override": {
                "request_error_rate": 0.4,
                "latency_p99_ms": 10000,
            },
        },
    )
    response = client.get("/api/v1/ops/incidents")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["trace_id"], str)
    assert isinstance(body["incidents"], list)
    assert len(body["incidents"]) >= 1
    assert "incident_id" in body["incidents"][0]
    assert "report_ref" in body["incidents"][0]
