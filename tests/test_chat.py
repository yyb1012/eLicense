# Time: 2026-04-18 22:12
# Description: 校验 /api/v1/chat 在 N09 质量门禁接入后的响应契约。
# Author: Feixue

from __future__ import annotations


def test_chat_placeholder_response(client):
    payload = {
        "session_id": "S-001",
        "work_order_id": "WO-001",
        "message": "hello",
        "user_id": "U-001",
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("[stub]")
    assert body["decision"]["route"] in {"pass", "degrade", "reject", "human_review"}
    assert body["risk_level"] in {"low", "medium", "high", "critical", "unknown"}
    assert body["next_action"] in {
        "proceed_to_writeback",
        "proceed_with_degrade_mode",
        "close_as_rejected",
        "escalate_to_human_review",
    }
    assert body["trace_id"]
    assert response.headers["x-trace-id"] == body["trace_id"]
