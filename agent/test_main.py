from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_agent_chat_response_does_not_expose_raw_state():
    response = client.post("/agent/chat", json={"message": "Where is my order?"})

    assert response.status_code == 200

    body = response.json()

    assert "rawState" not in body
    assert set(body.keys()) == {"message", "intent", "orderNumber", "uiState"}


def test_agent_chat_response_shape_for_a_specific_order():
    response = client.post("/agent/chat", json={"message": "Track U-1002"})

    assert response.status_code == 200

    body = response.json()

    assert "rawState" not in body
    assert body["intent"] == "SELECT_ORDER"
    assert body["orderNumber"] == "U-1002"
