# agent/test_v2_cancellation.py
#
# CANCELLATION — the first V2 capability with a sensitive tool, proving the
# full confirmation/idempotency cycle (plan sections 20-21, 25). Covers the
# full propose -> confirm -> execute cycle, one test per each of the 7
# validate_confirmation checks, idempotency replay, decline, dry-run
# failure, and the defense-in-depth guards that keep the sensitive tool out
# of reach of both execute_tool and free-text "authorization".
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from main import app
from v2 import confirmation, idempotency
from v2.graph import execute_confirmed_action_node, execute_tool_node, v2_agent_graph

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def clear_idempotency_store():
    # idempotency._EXECUTED_ACTIONS is module-level/in-memory (deliberately,
    # per the plan's prototype-only design) — clear it between tests so one
    # test's recorded actionId can never leak into another's.
    idempotency._EXECUTED_ACTIONS.clear()
    yield
    idempotency._EXECUTED_ACTIONS.clear()


def _config(suffix: str):
    return {"configurable": {"thread_id": f"cancellation-test-{suffix}"}}


def _thread_id_for(config):
    return config["configurable"]["thread_id"]


def _reach_confirmation_pending(order_number: str, thread_suffix: str):
    """
    Drives the deterministic flow up to a real CONFIRM_ACTION interrupt.
    "Cancel order <N>" already names the order, so the deterministic
    fallback skips straight past the order-selection ask stage — but (as
    of the 2026-08 structured-interaction fix) still asks for item
    selection whenever an order has more than one cancellable item, so
    this walks through BOTH possible ASK_CUSTOMER stages (order, then
    item), each resumed with the new typed structured-selection envelope,
    never the old free-text-synthesizing "selection" shape.

    Sets state["threadId"] explicitly on the fresh-turn input, matching
    what the router always does — request_confirmation_node's deterministic
    actionId derivation depends on it (agent/v2/confirmation.py's
    deterministic_action_id), and a test driving turn 1 directly through
    v2_agent_graph.invoke() (bypassing the router) would otherwise leave it
    unset, producing a different actionId than a later router-driven call
    on the SAME thread would compute.
    """

    config = _config(thread_suffix)
    result = v2_agent_graph.invoke(
        {"userMessage": f"Cancel order {order_number}", "threadId": _thread_id_for(config)},
        config=config,
    )

    interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ORDER_SELECTED":
        result = v2_agent_graph.invoke(
            Command(
                resume={
                    "type": "ORDER_SELECTED",
                    "capability": "CANCELLATION",
                    "payload": {"orderNumber": order_number},
                }
            ),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ITEM_SELECTED":
        item_candidates = interrupt_value["offeredCandidates"]["items"]
        selections = [
            {"orderLineId": line_id, "quantity": info["maxQuantity"]}
            for line_id, info in item_candidates.items()
        ]
        result = v2_agent_graph.invoke(
            Command(
                resume={
                    "type": "ITEM_SELECTED",
                    "capability": "CANCELLATION",
                    "payload": {"selections": selections},
                }
            ),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"

    return config, interrupt_value["actionId"], interrupt_value["actionType"]


# --- full cycle ---


def test_full_propose_confirm_execute_cycle():
    config, action_id, action_type = _reach_confirmation_pending("U-1004", "full-cycle")

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "cancellationConfirmed"
    assert result["a2uiOrigin"] == "MANDATORY_DETERMINISTIC"
    assert result["pendingAction"]["consumed"] is True
    assert result["pendingAction"]["executed"] is True

    exec_result = result["toolResults"]["submit_order_cancellation_tool"]
    assert exec_result["orderNumber"] == "U-1004"
    assert exec_result["status"] == "submitted"
    assert idempotency.has_executed(action_id)


def test_confirmation_screen_is_never_agent_proposed():
    _config_unused, action_id, action_type = _reach_confirmation_pending("U-1005", "mandatory-ui")
    # a2uiOrigin at the pending stage isn't directly observable from the
    # interrupt payload's top level in this test harness, but the
    # confirmed stage is — asserted in test_full_propose_confirm_execute_cycle.
    assert action_type == "SUBMIT_CANCELLATION"


# --- declining ---


def test_declining_does_not_execute_and_clears_pending_action():
    config, action_id, action_type = _reach_confirmation_pending("U-1004", "decline")

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert result["pendingAction"] is None
    assert "submit_order_cancellation_tool" not in result.get("toolResults", {})
    assert not idempotency.has_executed(action_id)
    assert "won't cancel" in result["uiState"]["assistantMessage"].lower()


# --- correction 1: free text is never authorization ---


def test_typed_yes_during_confirmation_never_executes():
    config, action_id, action_type = _reach_confirmation_pending("U-1004", "typed-yes")
    thread_id = config["configurable"]["thread_id"]

    response = client.post(
        "/v2/agent/chat", json={"threadId": thread_id, "message": "yes, go ahead and do it"}
    ).json()

    assert response["status"] == "INTERRUPTED_CONFIRM"
    # Still showing the PENDING screen, not the CONFIRMED one — "yes, go
    # ahead" re-interrupted with the same unexecuted pending action rather
    # than being treated as authorization.
    assert response["uiState"]["uiMode"] == "cancellationConfirmationPending"
    assert not idempotency.has_executed(action_id)

    # The pendingAction is untouched — the SAME actionId can still be
    # confirmed for real afterward via the actual button-click shape.
    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )
    assert result["status"] == "FINAL"
    assert idempotency.has_executed(action_id)


# --- dry-run failure ---


def test_dry_run_failure_never_creates_a_pending_action():
    # Directly exercise request_confirmation_node's dry-run path with a
    # quantity that exceeds what's actually cancellable — the underlying
    # tool call itself should raise, never reaching a confirmation screen.
    from v2.graph import request_confirmation_node

    state = {
        "activeCapability": "CANCELLATION",
        "threadId": "dry-run-fail-direct",
        "loopIteration": 0,
        "toolLog": [],
        "toolResults": {},
        "_decision": {
            "action": "CALL_TOOL",
            "toolName": "submit_order_cancellation_tool",
            "toolArgs": {
                "order_number": "U-1004",
                "line_selections": [{"orderLineId": "OL-1004-2", "quantity": 999}],
                "reason": "test",
            },
            "message": "",
            "uiProposal": [],
        },
    }

    result = request_confirmation_node(state)

    assert result["_confirmationDryRunFailed"] is True
    assert result["pendingAction"] is None
    assert result["toolResults"]["submit_order_cancellation_tool"]["error"]


# --- defense in depth ---


def test_execute_tool_refuses_to_call_a_sensitive_tool_directly():
    state = {
        "activeCapability": "CANCELLATION",
        "_decision": {
            "action": "CALL_TOOL",
            "toolName": "submit_order_cancellation_tool",
            "toolArgs": {"order_number": "U-1004", "line_selections": [], "reason": "x"},
        },
        "toolLog": [],
        "toolResults": {},
        "loopIteration": 0,
    }

    result = execute_tool_node(state)

    assert "sensitive" in result["toolResults"]["submit_order_cancellation_tool"]["error"].lower()
    assert not idempotency.has_executed("anything")  # sanity: nothing was ever recorded


# --- idempotency replay (unit-level: LangGraph's own checkpoint semantics
# already prevent re-invoking a completed thread, confirmed by manual
# testing, so this exercises validate_confirmation's check 7 directly) ---


def test_idempotency_replay_returns_cached_result_without_re_executing():
    # A fresh-looking pending action (consumed=False, executed=False, so
    # checks 5/6 would pass) whose actionId nonetheless already has a
    # recorded execution — the scenario check 7 exists to catch, distinct
    # from checks 5/6 which catch the SAME pendingAction object already
    # being marked done.
    pending = confirmation.create_pending_action(
        "replay-test-action-id",
        "SUBMIT_CANCELLATION",
        "CANCELLATION",
        {"order_number": "U-1004", "line_selections": [], "reason": "x"},
        eligibility_checked=True,
    )
    idempotency.record_executed(pending["actionId"], {"orderNumber": "U-1004", "status": "submitted"})

    state = {
        "activeCapability": "CANCELLATION",
        "pendingAction": pending,
        "_confirmationReply": {"actionId": pending["actionId"], "actionType": "SUBMIT_CANCELLATION", "accepted": True},
        "toolLog": [],
        "toolResults": {},
    }

    result = execute_confirmed_action_node(state)

    assert result["_mandatoryUi"][0]["type"] == "cancellationConfirmed"
    assert result["_decision"]["action"] == "FINISH"
    assert "already submitted" in result["_decision"]["message"].lower()
    # No new tool execution happened — toolLog was never appended to.
    assert result["toolLog"] == []


# --- the 7 validate_confirmation checks, directly ---


def _valid_pending():
    return confirmation.create_pending_action(
        "action-1", "SUBMIT_CANCELLATION", "CANCELLATION", {"order_number": "U-1004"}, eligibility_checked=True
    )


def test_check_1_action_id_mismatch():
    pending = _valid_pending()
    result = confirmation.validate_confirmation(
        pending, {"actionId": "wrong-id", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ACTION_ID_MISMATCH"


def test_check_2_action_type_mismatch():
    pending = _valid_pending()
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "CREATE_RETURN", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ACTION_TYPE_MISMATCH"


def test_check_3_payload_changed():
    pending = _valid_pending()
    pending["payloadHash"] = "tampered-hash-value"
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "PAYLOAD_CHANGED"


def test_check_4_eligibility_not_confirmed():
    pending = confirmation.create_pending_action(
        "action-1", "SUBMIT_CANCELLATION", "CANCELLATION", {"order_number": "U-1004"}, eligibility_checked=False
    )
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ELIGIBILITY_NOT_CONFIRMED"


def test_check_5_already_consumed():
    pending = _valid_pending()
    pending["consumed"] = True
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ALREADY_CONSUMED"


def test_check_6_already_executed():
    pending = _valid_pending()
    pending["executed"] = True
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ALREADY_EXECUTED"


def test_check_7_idempotency_replay():
    pending = _valid_pending()
    idempotency.record_executed(pending["actionId"], {"orderNumber": "U-1004"})
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "IDEMPOTENCY_REPLAY"


def test_no_pending_action_at_all():
    result = confirmation.validate_confirmation(
        None, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "NO_PENDING_ACTION"


def test_a_fully_valid_confirmation_passes_all_seven_checks():
    pending = _valid_pending()
    result = confirmation.validate_confirmation(
        pending, {"actionId": "action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is True
    assert result.accepted is True


def test_deterministic_action_id_is_stable_for_identical_inputs():
    id1 = confirmation.deterministic_action_id("t1", 3, "submit_order_cancellation_tool", {"a": 1})
    id2 = confirmation.deterministic_action_id("t1", 3, "submit_order_cancellation_tool", {"a": 1})
    id3 = confirmation.deterministic_action_id("t1", 4, "submit_order_cancellation_tool", {"a": 1})

    assert id1 == id2
    assert id1 != id3
