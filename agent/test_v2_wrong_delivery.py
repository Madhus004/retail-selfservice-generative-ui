# agent/test_v2_wrong_delivery.py
#
# WRONG_DELIVERY — reuses Phase 4's confirmation/idempotency machinery
# unchanged (plan section 32, Phase 5). The 7 validate_confirmation checks
# and the general __confirmationReminder__/idempotency mechanics are
# capability-agnostic and already fully covered by test_v2_cancellation.py;
# this file spot-checks a couple of them for this capability plus the
# parts that are genuinely new here: the new submit_wrong_delivery_claim
# deterministic function (404/409/400), the no-order-number free-text ask
# flow (this capability has no "list eligible orders" tool, unlike
# ORDER_STATUS/CANCELLATION), and the retry-limit-escalates-a-persistently-
# invalid-claim fix caught while building this phase.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from langgraph.types import Command

from main import app
from v2 import confirmation, idempotency, loop_safety
from v2.graph import v2_agent_graph
from v2.tools.wrong_delivery_tools import submit_wrong_delivery_claim

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
    return {"configurable": {"thread_id": f"wrong-delivery-test-{suffix}"}}


# --- the new deterministic function, directly ---


def test_submit_claim_succeeds_for_a_delivered_order():
    result = submit_wrong_delivery_claim("U-1002", "Package shows delivered but I never got it.")

    assert result["orderNumber"] == "U-1002"
    assert result["status"] == "submitted"
    assert result["claimId"].startswith("CLAIM-U1002-")


def test_submit_claim_rejects_unknown_order():
    with pytest.raises(HTTPException) as exc_info:
        submit_wrong_delivery_claim("U-9999", "x")
    assert exc_info.value.status_code == 404


def test_submit_claim_rejects_an_order_that_was_never_delivered():
    with pytest.raises(HTTPException) as exc_info:
        submit_wrong_delivery_claim("U-1003", "x")  # in transit, not delivered
    assert exc_info.value.status_code == 409


def test_submit_claim_rejects_an_empty_description():
    with pytest.raises(HTTPException) as exc_info:
        submit_wrong_delivery_claim("U-1002", "   ")
    assert exc_info.value.status_code == 400


# --- the no-order-number free-text ask flow (new: no "list orders" tool here) ---


def test_asks_for_order_number_as_free_text_when_none_given():
    config = _config("ask-order-number")
    result = v2_agent_graph.invoke(
        {"userMessage": "It says delivered but I never received it.", "threadId": _thread_id(config)},
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    # No structured order list is offered — this capability has no
    # get_recent_orders-style tool, unlike ORDER_STATUS/CANCELLATION.
    assert interrupt_value["uiState"]["uiMode"] == "welcome"


def test_continuing_with_a_typed_order_number_reaches_confirmation():
    config = _config("continue-with-order-number")
    v2_agent_graph.invoke(
        {"userMessage": "It says delivered but I never received it.", "threadId": _thread_id(config)},
        config=config,
    )

    result = v2_agent_graph.invoke(Command(resume={"customerReply": "U-1002"}), config=config)

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    assert interrupt_value["actionType"] == "SUBMIT_WRONG_DELIVERY_CLAIM"


def _thread_id(config):
    return config["configurable"]["thread_id"]


# --- full cycle, using an order number given up front ---


def _reach_confirmation_pending(order_number: str, thread_suffix: str):
    config = _config(thread_suffix)
    result = v2_agent_graph.invoke(
        {
            "userMessage": f"It says delivered but I never received order {order_number}.",
            "threadId": _thread_id(config),
        },
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
    assert result["uiState"]["uiMode"] == "claimSubmitted"
    assert result["a2uiOrigin"] == "MANDATORY_DETERMINISTIC"
    assert result["pendingAction"]["executed"] is True

    exec_result = result["toolResults"]["submit_wrong_delivery_claim_tool"]
    assert exec_result["orderNumber"] == "U-1002"
    assert idempotency.has_executed(action_id)


def test_declining_does_not_submit_a_claim():
    config, action_id, action_type = _reach_confirmation_pending("U-1002", "decline")

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert result["pendingAction"] is None
    assert "submit_wrong_delivery_claim_tool" not in result.get("toolResults", {})
    assert not idempotency.has_executed(action_id)


def test_typed_yes_during_confirmation_never_submits_a_claim():
    config, action_id, action_type = _reach_confirmation_pending("U-1002", "typed-yes")
    thread_id = _thread_id(config)

    response = client.post(
        "/v2/agent/chat", json={"threadId": thread_id, "message": "yes go ahead"}
    ).json()

    assert response["status"] == "INTERRUPTED_CONFIRM"
    assert response["uiState"]["uiMode"] == "claimConfirmationPending"
    assert not idempotency.has_executed(action_id)


# --- the retry-limit fix: a persistently-invalid claim escalates, doesn't loop forever ---


def test_an_order_that_can_never_be_claimed_escalates_via_retry_limit_not_iteration_cap():
    config = _config("retry-limit")
    result = v2_agent_graph.invoke(
        {
            "userMessage": "It says delivered but I never received order U-1003.",  # never delivered -> always 409
            "threadId": _thread_id(config),
        },
        config=config,
    )

    assert result["status"] == "ERROR"
    assert result["_escalationReason"] == "tool_retry_limit_exceeded:submit_wrong_delivery_claim_tool"
    # Escalated well before the 8-iteration cap — proves the dedicated
    # retry-limit check in request_confirmation_node's dry-run path fired,
    # not just the generic iteration budget.
    assert result["loopIteration"] < loop_safety.MAX_LOOP_ITERATIONS


# --- confirmation machinery reuse, spot-checked (full 7-check coverage lives in test_v2_cancellation.py) ---


def test_action_type_mismatch_is_rejected_for_this_capability_too():
    pending = confirmation.create_pending_action(
        "wd-action-1",
        "SUBMIT_WRONG_DELIVERY_CLAIM",
        "WRONG_DELIVERY",
        {"order_number": "U-1002", "description": "x"},
        eligibility_checked=True,
    )
    result = confirmation.validate_confirmation(
        pending, {"actionId": "wd-action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ACTION_TYPE_MISMATCH"


def test_idempotency_replay_works_for_this_capability_too():
    pending = confirmation.create_pending_action(
        "wd-action-2",
        "SUBMIT_WRONG_DELIVERY_CLAIM",
        "WRONG_DELIVERY",
        {"order_number": "U-1002", "description": "x"},
        eligibility_checked=True,
    )
    idempotency.record_executed(pending["actionId"], {"claimId": "CLAIM-U1002-ABC123"})

    result = confirmation.validate_confirmation(
        pending, {"actionId": "wd-action-2", "actionType": "SUBMIT_WRONG_DELIVERY_CLAIM", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "IDEMPOTENCY_REPLAY"
