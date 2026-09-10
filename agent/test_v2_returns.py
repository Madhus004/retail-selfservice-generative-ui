# agent/test_v2_returns.py
#
# RETURNS — the fourth and last V2 capability (plan section 32, Phase 6),
# reusing Phase 4's confirmation/idempotency machinery unchanged, same as
# WRONG_DELIVERY did. The 7 validate_confirmation checks and the general
# __confirmationReminder__/idempotency mechanics are capability-agnostic and
# already fully covered by test_v2_cancellation.py; this file spot-checks a
# couple of them for this capability plus what's genuinely new here: the new
# get_return_eligible_items/create_return deterministic functions
# (404/409/400 + refund-estimate math), the multi-order structured
# order-selection ask flow (this capability has no single "list eligible
# orders" tool the way CANCELLATION does — it reuses get_recent_orders_tool,
# which surfaces every order, eligible or not), and the tampered-selection
# rejection this shares in shape with CANCELLATION's own coverage.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from langgraph.types import Command

from main import app
from v2 import confirmation, idempotency
from v2.graph import v2_agent_graph
from v2.tools.returns_tools import create_return, get_return_eligible_items

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def clear_idempotency_store():
    idempotency._EXECUTED_ACTIONS.clear()
    yield
    idempotency._EXECUTED_ACTIONS.clear()


def _config(suffix: str):
    return {"configurable": {"thread_id": f"returns-test-{suffix}"}}


def _thread_id_for(config):
    return config["configurable"]["thread_id"]


# --- the new deterministic functions, directly ---


def test_get_return_eligible_items_for_an_eligible_order():
    result = get_return_eligible_items("U-1001")

    assert result["eligible"] is True
    assert result["returnWindowExpiresAt"] == "2026-06-03"
    assert len(result["items"]) == 2


def test_get_return_eligible_items_for_an_ineligible_order():
    result = get_return_eligible_items("U-1003")

    assert result["eligible"] is False
    assert "hasn't been delivered" in result["reason"]
    assert result["items"] == []


def test_get_return_eligible_items_rejects_unknown_order():
    with pytest.raises(HTTPException) as exc_info:
        get_return_eligible_items("U-9999")
    assert exc_info.value.status_code == 404


def test_create_return_succeeds_and_computes_refund_estimate():
    result = create_return(
        "U-1001",
        [{"orderLineId": "OL-1001-1", "quantity": 1}, {"orderLineId": "OL-1001-2", "quantity": 2}],
        "wrong size",
    )

    assert result["orderNumber"] == "U-1001"
    assert result["status"] == "submitted"
    assert result["returnId"].startswith("RTN-U1001-")
    # 98.00 * 1 + 15.21 * 2 = 128.42
    assert result["refundEstimate"] == 128.42


def test_create_return_rejects_unknown_order():
    with pytest.raises(HTTPException) as exc_info:
        create_return("U-9999", [{"orderLineId": "OL-1-1", "quantity": 1}], "x")
    assert exc_info.value.status_code == 404


def test_create_return_rejects_an_ineligible_order():
    with pytest.raises(HTTPException) as exc_info:
        create_return("U-1003", [{"orderLineId": "OL-1003-1", "quantity": 1}], "x")
    assert exc_info.value.status_code == 409


def test_create_return_rejects_an_empty_selection():
    with pytest.raises(HTTPException) as exc_info:
        create_return("U-1001", [], "x")
    assert exc_info.value.status_code == 400


def test_create_return_rejects_an_unknown_line_id():
    with pytest.raises(HTTPException) as exc_info:
        create_return("U-1001", [{"orderLineId": "OL-9999-1", "quantity": 1}], "x")
    assert exc_info.value.status_code == 400


def test_create_return_rejects_a_quantity_over_the_returnable_amount():
    with pytest.raises(HTTPException) as exc_info:
        create_return("U-1001", [{"orderLineId": "OL-1001-2", "quantity": 5}], "x")
    assert exc_info.value.status_code == 400


# --- the multi-order structured order-selection ask flow ---


def test_asks_which_order_when_none_named_and_multiple_exist():
    config = _config("ask-order")
    result = v2_agent_graph.invoke(
        {"userMessage": "I want to return something.", "threadId": _thread_id_for(config)},
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "ORDER_SELECTED"
    assert interrupt_value["uiState"]["uiMode"] == "orderSelection"
    offered = interrupt_value["offeredCandidates"]["orderNumbers"]
    assert "U-1001" in offered
    assert "U-1002" in offered
    # get_return_eligible_orders_tool (2026-08 structured-interaction fix)
    # only ever offers return-eligible orders — U-1003/U-1004/U-1005 are
    # in-transit/not-yet-shipped and must never appear here (previously
    # RETURNS reused get_recent_orders_tool, which listed all five).
    assert "U-1003" not in offered
    assert "U-1004" not in offered
    assert "U-1005" not in offered


def test_tampered_order_selection_outside_the_offered_set_is_rejected():
    config = _config("tampered-selection")
    v2_agent_graph.invoke(
        {"userMessage": "I want to return something.", "threadId": _thread_id_for(config)},
        config=config,
    )

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "RETURNS",
                "payload": {"orderNumber": "U-9999"},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert "doesn't match" in interrupt_value["message"].lower()


def test_selecting_an_offered_order_proceeds_to_the_reason_stage():
    """
    U-1002 has only one returnable item, so item selection auto-skips —
    but a reason is always asked (2026-08 structured-interaction fix), so
    the very next stage after a valid order selection is REASON_SELECTED,
    not straight to confirmation.
    """

    config = _config("select-order")
    v2_agent_graph.invoke(
        {"userMessage": "I want to return something.", "threadId": _thread_id_for(config)},
        config=config,
    )

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "RETURNS",
                "payload": {"orderNumber": "U-1002"},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "REASON_SELECTED"
    assert interrupt_value["uiState"]["uiMode"] == "returnReasonPrompt"
    # Never synthesized into prose — the root cause of the "Track U-1001"
    # bug this fix addresses generalizes to every structured selection.
    assert "track" not in result["userMessage"].lower()


# --- ineligible order finishes cleanly, no confirmation ever offered ---


def test_ineligible_order_named_up_front_finishes_without_a_pending_action():
    config = _config("ineligible")
    result = v2_agent_graph.invoke(
        {"userMessage": "I want to return order U-1003.", "threadId": _thread_id_for(config)},
        config=config,
    )

    assert "__interrupt__" not in result
    assert result["status"] == "FINAL"
    assert result.get("pendingAction") is None
    assert "hasn't been delivered" in result["uiState"]["assistantMessage"]


# --- full cycle, using an order number given up front ---


def _reach_confirmation_pending(order_number: str, thread_suffix: str):
    """
    Drives the deterministic flow up to a real CONFIRM_ACTION interrupt,
    walking through whichever ASK_CUSTOMER stages are actually required
    (item selection when there's more than one returnable item, reason
    always, method when more than one is available) — each resumed with
    the typed structured-selection envelope, never the old free-text-
    synthesizing "selection" shape.
    """

    config = _config(thread_suffix)
    result = v2_agent_graph.invoke(
        {"userMessage": f"I want to return order {order_number}.", "threadId": _thread_id_for(config)},
        config=config,
    )

    interrupt_value = result["__interrupt__"][0].value

    while interrupt_value["interruptType"] == "ASK_CUSTOMER":
        interaction_type = interrupt_value["expectedInteractionType"]
        candidates = interrupt_value["offeredCandidates"]

        if interaction_type == "ITEM_SELECTED":
            selections = [
                {"orderLineId": line_id, "quantity": info["maxQuantity"]}
                for line_id, info in candidates["items"].items()
            ]
            payload = {"selections": selections}
        elif interaction_type == "REASON_SELECTED":
            payload = {"reason": candidates["reasons"][0]}
        elif interaction_type == "RETURN_METHOD_SELECTED":
            payload = {"method": candidates["methods"][0]}
        else:
            raise AssertionError(f"Unexpected ASK_CUSTOMER stage: {interaction_type}")

        result = v2_agent_graph.invoke(
            Command(resume={"type": interaction_type, "capability": "RETURNS", "payload": payload}),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"

    return config, interrupt_value["actionId"], interrupt_value["actionType"]


def test_full_propose_confirm_execute_cycle():
    config, action_id, action_type = _reach_confirmation_pending("U-1002", "full-cycle")

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "returnSubmitted"
    assert result["a2uiOrigin"] == "MANDATORY_DETERMINISTIC"
    assert result["pendingAction"]["executed"] is True

    exec_result = result["toolResults"]["create_return_tool"]
    assert exec_result["orderNumber"] == "U-1002"
    assert exec_result["refundEstimate"] == 79.22
    assert idempotency.has_executed(action_id)


def test_declining_does_not_submit_a_return():
    config, action_id, action_type = _reach_confirmation_pending("U-1002", "decline")

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert result["pendingAction"] is None
    assert "create_return_tool" not in result.get("toolResults", {})
    assert not idempotency.has_executed(action_id)


def test_typed_yes_during_confirmation_never_submits_a_return():
    config, action_id, action_type = _reach_confirmation_pending("U-1002", "typed-yes")
    thread_id = _thread_id_for(config)

    response = client.post(
        "/v2/agent/chat", json={"threadId": thread_id, "message": "yes go ahead"}
    ).json()

    assert response["status"] == "INTERRUPTED_CONFIRM"
    assert response["uiState"]["uiMode"] == "returnConfirmationPending"
    assert not idempotency.has_executed(action_id)

    # The pendingAction is untouched — the SAME actionId can still be
    # confirmed for real afterward via the actual button-click shape.
    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )
    assert result["status"] == "FINAL"
    assert idempotency.has_executed(action_id)


# --- confirmation machinery reuse, spot-checked (full 7-check coverage lives in test_v2_cancellation.py) ---


def test_action_type_mismatch_is_rejected_for_this_capability_too():
    pending = confirmation.create_pending_action(
        "ret-action-1",
        "CREATE_RETURN",
        "RETURNS",
        {"order_number": "U-1002", "line_selections": [], "reason": "x"},
        eligibility_checked=True,
    )
    result = confirmation.validate_confirmation(
        pending, {"actionId": "ret-action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ACTION_TYPE_MISMATCH"


def test_idempotency_replay_works_for_this_capability_too():
    pending = confirmation.create_pending_action(
        "ret-action-2",
        "CREATE_RETURN",
        "RETURNS",
        {"order_number": "U-1002", "line_selections": [], "reason": "x"},
        eligibility_checked=True,
    )
    idempotency.record_executed(pending["actionId"], {"returnId": "RTN-U1002-ABC123"})

    result = confirmation.validate_confirmation(
        pending, {"actionId": "ret-action-2", "actionType": "CREATE_RETURN", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "IDEMPOTENCY_REPLAY"
