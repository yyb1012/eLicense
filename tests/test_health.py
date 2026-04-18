# Time: 2026-04-18 15:50
# Description: 校验 /health 接口的状态与 trace_id 字段。
# Author: Feixue

from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["trace_id"], str)
    assert body["trace_id"]
