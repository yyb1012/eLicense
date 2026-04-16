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
    assert body["decision"]["route"] == "pass"
    assert body["risk_level"] == "unknown"
    assert body["trace_id"]
    assert response.headers["x-trace-id"] == body["trace_id"]
