import pytest
from fastapi.testclient import TestClient

from graph import build_default_a2ui_payload, build_ui_state_node, fallback_intent_detection
from main import app
from tools import get_cancellation_eligible_orders, submit_order_cancellation

client = TestClient(app)


# --- tools.py: pure function tests (deterministic, no HTTP/LLM involved) ---


def test_get_cancellation_eligible_orders_only_includes_eligible_orders():
    result = get_cancellation_eligible_orders()
    order_numbers = {order["orderNumber"] for order in result["orders"]}

    assert order_numbers == {"U-1004", "U-1005"}


def test_submit_order_cancellation_succeeds_for_valid_partial_request():
    result = submit_order_cancellation(
        "U-1004",
        [{"orderLineId": "OL-1004-2", "quantity": 1}],
        "No longer needed",
    )

    assert result["orderNumber"] == "U-1004"
    assert result["status"] == "submitted"
    assert result["resultingOrderStatus"] == "Partially cancelled"
    assert result["cancelledItems"] == [
        {
            "itemName": "Everyday Crew Tee",
            "color": "Heather Grey",
            "size": "M",
            "quantity": 1,
        }
    ]


def test_submit_order_cancellation_is_side_effect_free():
    # Calling it once should not change what a later call sees as cancellable
    # — the tool never mutates the mock data (see tools.py docstring).
    before = get_cancellation_eligible_orders()
    submit_order_cancellation(
        "U-1004", [{"orderLineId": "OL-1004-1", "quantity": 1}], "test"
    )
    after = get_cancellation_eligible_orders()

    assert before == after


def test_submit_order_cancellation_rejects_quantity_beyond_cancellable():
    with pytest.raises(Exception) as exc_info:
        submit_order_cancellation(
            "U-1004", [{"orderLineId": "OL-1004-2", "quantity": 5}], "x"
        )

    assert exc_info.value.status_code == 400


def test_submit_order_cancellation_rejects_ineligible_order():
    with pytest.raises(Exception) as exc_info:
        submit_order_cancellation(
            "U-1002", [{"orderLineId": "OL-1002-1", "quantity": 1}], "x"
        )

    assert exc_info.value.status_code == 409


def test_submit_order_cancellation_rejects_unknown_order():
    with pytest.raises(Exception) as exc_info:
        submit_order_cancellation("U-9999", [{"orderLineId": "x", "quantity": 1}], "x")

    assert exc_info.value.status_code == 404


def test_submit_order_cancellation_rejects_unknown_line_id():
    with pytest.raises(Exception) as exc_info:
        submit_order_cancellation(
            "U-1004", [{"orderLineId": "NOPE", "quantity": 1}], "x"
        )

    assert exc_info.value.status_code == 400


def test_submit_order_cancellation_rejects_empty_selection():
    with pytest.raises(Exception) as exc_info:
        submit_order_cancellation("U-1004", [], "x")

    assert exc_info.value.status_code == 400


# --- graph.py: intent classification and UI-state shape ---


def test_fallback_detects_cancel_order_intent():
    state = {"userMessage": "Cancel an order"}
    result = fallback_intent_detection(state)

    assert result["intent"] == "CANCEL_ORDER"


def test_fallback_cancel_order_wins_over_explicit_order_number():
    state = {"userMessage": "Cancel order U-1004"}
    result = fallback_intent_detection(state)

    assert result["intent"] == "CANCEL_ORDER"
    assert result["orderNumber"] == "U-1004"


def test_default_a2ui_payload_for_cancel_order():
    payload = build_default_a2ui_payload({"intent": "CANCEL_ORDER"})

    assert payload == [
        {"type": "cancellationBuilder", "props": {"dataKey": "eligibleOrders"}}
    ]


def test_build_ui_state_for_cancel_order_with_eligible_orders():
    state = {
        "intent": "CANCEL_ORDER",
        "cancellationEligibleOrdersData": {
            "customer": {"name": "Demo Customer"},
            "orders": [{"orderNumber": "U-1004", "items": []}],
        },
    }

    result = build_ui_state_node(state)
    ui_state = result["uiState"]

    assert ui_state["uiMode"] == "cancellationBuilder"
    assert ui_state["canvasData"]["eligibleOrders"] == [
        {"orderNumber": "U-1004", "items": []}
    ]
    assert ui_state["a2ui"][0]["type"] == "cancellationBuilder"


def test_build_ui_state_for_cancel_order_with_no_eligible_orders():
    state = {
        "intent": "CANCEL_ORDER",
        "cancellationEligibleOrdersData": {"customer": {}, "orders": []},
    }

    result = build_ui_state_node(state)

    assert "cancelled" in result["uiState"]["assistantMessage"].lower()


# --- main.py: REST endpoints (deterministic, no LLM involved) ---


def test_cancellation_eligible_orders_endpoint():
    response = client.get("/customers/demo/cancellation-eligible-orders")

    assert response.status_code == 200
    order_numbers = {order["orderNumber"] for order in response.json()["orders"]}
    assert order_numbers == {"U-1004", "U-1005"}


def test_order_cancellation_endpoint_success():
    response = client.post(
        "/orders/U-1004/cancellation",
        json={
            "lineSelections": [{"orderLineId": "OL-1004-1", "quantity": 1}],
            "reason": "Found a better price",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["orderNumber"] == "U-1004"
    assert body["reason"] == "Found a better price"


def test_order_cancellation_endpoint_rejects_ineligible_order():
    response = client.post(
        "/orders/U-1001/cancellation",
        json={
            "lineSelections": [{"orderLineId": "OL-1001-1", "quantity": 1}],
            "reason": "x",
        },
    )

    assert response.status_code == 409
