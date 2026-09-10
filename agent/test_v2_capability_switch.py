# agent/test_v2_capability_switch.py
#
# Phase 7 — capability switching, CLARIFY, and UNSUPPORTED (plan sections
# 16-17, 18). Covers what test_v2_interrupt_pivot.py's mechanism-focused
# suite doesn't: BETWEEN-TURNS switching (no pending interrupt at pivot
# time — turn 1 finishes normally, turn 2 arrives fresh and names a
# different capability), walkthrough F (order number carries across a
# between-turns switch via lastKnownOrderNumber), enforce_capability_switch
# leaving a genuinely unrelated turn alone (no switch, nothing reset), and
# the two new terminal/redirect nodes this phase adds.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from main import app
from v2.graph import (
    _compute_workflow_stage,
    _resolve_order_number,
    enforce_capability_switch_node,
    v2_agent_graph,
)
from v2 import loop_safety

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _config(suffix: str):
    return {"configurable": {"thread_id": f"cap-switch-test-{suffix}"}}


def _thread_id_for(config):
    return config["configurable"]["thread_id"]


# --- between-turns switching resets session-scoped state ---


def test_switching_capability_between_turns_resets_tool_results_and_iteration():
    config = _config("reset-state")
    r1 = v2_agent_graph.invoke(
        {"userMessage": "Where is order U-1002?", "threadId": _thread_id_for(config)}, config=config
    )
    assert r1["status"] == "FINAL"
    assert r1["toolResults"]  # ORDER_STATUS actually looked something up

    r2 = v2_agent_graph.invoke({"userMessage": "Cancel order U-1004"}, config=config)

    assert r2["activeCapability"] == "CANCELLATION"
    assert r2["capabilityTransition"]["from"] == "ORDER_STATUS"
    assert r2["capabilityTransition"]["to"] == "CANCELLATION"
    assert r2["capabilityTransition"]["clearedPending"] is False  # nothing was pending
    # ORDER_STATUS's tool results don't leak into CANCELLATION's turn.
    assert "get_order_status_tool" not in r2["toolResults"]


def test_switching_into_the_same_capability_is_not_treated_as_a_switch():
    config = _config("no-op-switch")
    v2_agent_graph.invoke(
        {"userMessage": "Where is order U-1002?", "threadId": _thread_id_for(config)}, config=config
    )
    r2 = v2_agent_graph.invoke({"userMessage": "Why is it late?"}, config=config)

    # Still ORDER_STATUS both turns — enforce_capability_switch must not
    # report a transition (and must not reset state) for a same-capability
    # continuation, even one shaped like a fresh classification.
    assert r2["activeCapability"] == "ORDER_STATUS"
    assert r2.get("capabilityTransition") is None


# --- walkthrough F: order number carries across a between-turns switch ---


def test_walkthrough_f_order_number_carries_across_a_between_turns_switch():
    config = _config("walkthrough-f")
    r1 = v2_agent_graph.invoke(
        {"userMessage": "Where is order U-1002?", "threadId": _thread_id_for(config)}, config=config
    )
    assert r1["status"] == "FINAL"
    assert r1["lastKnownOrderNumber"] == "U-1002"

    r2 = v2_agent_graph.invoke(
        {"userMessage": "It says delivered but I never got it."}, config=config
    )

    # No order number in turn 2's message at all — WRONG_DELIVERY still
    # reaches a real CONFIRM_ACTION interrupt for U-1002 instead of
    # re-asking, unlike V1's stateless single-call design (plan
    # walkthrough F).
    assert r2["activeCapability"] == "WRONG_DELIVERY"
    assert "__interrupt__" in r2
    interrupt_value = r2["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    assert interrupt_value["actionType"] == "SUBMIT_WRONG_DELIVERY_CLAIM"


def test_last_known_order_number_fallback_only_applies_right_after_a_switch():
    """
    The fallback must not leak into an ordinary later turn within the SAME
    capability — otherwise "what about my other order?" would silently
    reuse a stale order instead of asking/listing normally. Tested directly
    against _resolve_order_number rather than through the full classifier
    cascade, since which deterministic capability a given phrase lands on
    is a separate concern from this fallback's own on/off condition.
    """

    state_no_switch_this_turn = {
        "_classification": {"orderNumber": None},
        "userMessage": "What about my other order?",
        "capabilityTransition": None,
        "lastKnownOrderNumber": "U-1002",
    }
    assert _resolve_order_number(state_no_switch_this_turn) is None

    state_just_switched = {
        "_classification": {"orderNumber": None},
        "userMessage": "It says delivered but I never got it.",
        "capabilityTransition": {"from": "ORDER_STATUS", "to": "WRONG_DELIVERY"},
        "lastKnownOrderNumber": "U-1002",
    }
    assert _resolve_order_number(state_just_switched) == "U-1002"


def test_last_known_order_number_fallback_never_fires_for_a_same_capability_transition():
    """
    Regression (found via a live thread log): clicking the "Track a
    different order" suggested-reply chip sends free text with no order
    number, and the classifier judged it isCapabilitySwitch=True even
    though it resolved to the SAME capability (ORDER_STATUS -> ORDER_STATUS)
    — enforce_capability_switch_node still sets a truthy capabilityTransition
    for that. Before this fix, _resolve_order_number's guard only checked
    "capabilityTransition is truthy," so it silently reused the order the
    customer had JUST asked to move on from, and the agent answered about
    that same order again instead of listing orders / asking which one —
    the exact opposite of what "a DIFFERENT order" means. Real cross-
    capability transitions (from != to, the walkthrough F case covered
    above) must still carry the order forward.
    """

    state_same_capability_transition = {
        "_classification": {"orderNumber": None},
        "userMessage": "Track a different order",
        "capabilityTransition": {"from": "ORDER_STATUS", "to": "ORDER_STATUS"},
        "lastKnownOrderNumber": "U-1003",
    }
    assert _resolve_order_number(state_same_capability_transition) is None


# --- enforce_capability_switch's archiving, exercised directly (companion
# to test_v2_interrupt_pivot.py's synthetic-capability version, now using a
# real second capability since all four are registered) ---


def test_enforce_capability_switch_archives_a_real_pending_action_on_switch():
    state = {
        "activeCapability": "RETURNS",
        "_classification": {
            "capability": "CANCELLATION",
            "confidence": "high",
            "isCapabilitySwitch": True,
            "orderNumber": "U-1004",
            "rationale": "test",
        },
        "pendingAction": {"actionId": "ret-action-1", "consumed": False, "executed": False},
        "toolResults": {"get_return_eligible_items_tool": {"orderNumber": "U-1001"}},
    }

    result = enforce_capability_switch_node(state)

    assert result["activeCapability"] == "CANCELLATION"
    assert result["pendingAction"] is None
    assert result["archivedPendingActions"][0]["actionId"] == "ret-action-1"
    assert result["toolResults"] == {}
    assert result["capabilityTransition"]["clearedPending"] is True


# --- regression: a stale EXECUTED pendingAction left behind by a PREVIOUS
# capability must never suppress the new capability's own mandatory-ask
# gate. Found via a live thread log: a CANCELLATION completed normally,
# then the same thread switched to RETURNS with 2 return-eligible orders —
# enforce_capability_switch_node only archives/clears a pendingAction that
# is still unconsumed (an already-executed one is deliberately left as a
# record), so RETURNS inherited CANCELLATION's finished pendingAction.
# _compute_workflow_stage's first check read that stale pendingAction and
# returned "COMPLETED" unconditionally, without checking which capability
# it actually belonged to — silently disabling agent_reason's deterministic
# gate for the rest of the thread and letting the LLM's own (wrong) FINISH
# decision through ungated, producing prose instead of a real orderSelection
# interrupt.


def test_compute_workflow_stage_ignores_a_stale_executed_pending_action_from_a_different_capability():
    state = {
        "activeCapability": "RETURNS",
        "pendingAction": {
            "actionId": "old-cancellation-action",
            "actionType": "SUBMIT_CANCELLATION",
            "capability": "CANCELLATION",
            "consumed": True,
            "executed": True,
        },
        "toolResults": {
            "get_return_eligible_orders_tool": {
                "orders": [
                    {"orderNumber": "U-1001", "items": []},
                    {"orderNumber": "U-1002", "items": []},
                ]
            }
        },
    }

    assert _compute_workflow_stage(state) == "WAITING_FOR_ORDER_SELECTION"


def test_stale_completed_cancellation_does_not_block_the_returns_ask_gate_end_to_end():
    config = _config("stale-pending-across-switch")
    thread_id = _thread_id_for(config)

    # Turn 1: run CANCELLATION all the way through a real confirm+execute.
    result = v2_agent_graph.invoke(
        {"userMessage": "Cancel order U-1004", "threadId": thread_id}, config=config
    )
    interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ORDER_SELECTED":
        result = v2_agent_graph.invoke(
            Command(resume={"type": "ORDER_SELECTED", "capability": "CANCELLATION", "payload": {"orderNumber": "U-1004"}}),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ITEM_SELECTED":
        item_candidates = interrupt_value["offeredCandidates"]["items"]
        selections = [{"orderLineId": line_id, "quantity": info["maxQuantity"]} for line_id, info in item_candidates.items()]
        result = v2_agent_graph.invoke(
            Command(resume={"type": "ITEM_SELECTED", "capability": "CANCELLATION", "payload": {"selections": selections}}),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    action_id, action_type = interrupt_value["actionId"], interrupt_value["actionType"]

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )
    assert result["status"] == "FINAL"
    assert result["pendingAction"]["executed"] is True  # confirms the stale-state precondition is real

    # Turn 2, same thread: switch to RETURNS. Two orders are return-eligible
    # for this demo customer (U-1001, U-1002), so this MUST land on a real
    # ASK_CUSTOMER orderSelection interrupt, never a FINAL/FINISH turn.
    result2 = v2_agent_graph.invoke(
        {"userMessage": "Actually, I want to return something else", "threadId": thread_id}, config=config
    )

    assert "__interrupt__" in result2, "RETURNS reached FINISH ungated instead of asking which order to return"
    interrupt_value2 = result2["__interrupt__"][0].value
    assert interrupt_value2["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value2["expectedInteractionType"] == "ORDER_SELECTED"


# --- CLARIFY: too vague to route, capped, re-classifies the answer ---


def test_clarify_asks_via_a_real_interrupt():
    config = _config("clarify-ask")
    result = v2_agent_graph.invoke(
        {"userMessage": "I need help.", "threadId": _thread_id_for(config)}, config=config
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert result["activeCapability"] == "CLARIFY"


def test_clarify_answer_reclassifies_into_a_real_capability():
    config = _config("clarify-resolve")
    v2_agent_graph.invoke(
        {"userMessage": "I need help.", "threadId": _thread_id_for(config)}, config=config
    )

    result = v2_agent_graph.invoke(
        Command(resume={"customerReply": "I want to cancel order U-1004"}), config=config
    )

    assert result["activeCapability"] == "CANCELLATION"


def test_three_consecutive_clarifies_escalate_instead_of_looping_forever():
    config = _config("clarify-escalate")
    v2_agent_graph.invoke({"userMessage": "help", "threadId": _thread_id_for(config)}, config=config)
    v2_agent_graph.invoke(Command(resume={"customerReply": "stuff"}), config=config)
    result = v2_agent_graph.invoke(Command(resume={"customerReply": "not sure"}), config=config)

    assert result["status"] == "ERROR"
    assert result["_escalationReason"] == "clarify_attempts_exceeded"
    assert "__interrupt__" not in result


def test_clarify_attempts_resets_once_a_real_capability_is_established():
    config = _config("clarify-reset")
    v2_agent_graph.invoke({"userMessage": "help", "threadId": _thread_id_for(config)}, config=config)  # attempt 1
    result = v2_agent_graph.invoke(
        Command(resume={"customerReply": "actually, where is order U-1002"}), config=config
    )

    assert result["activeCapability"] == "ORDER_STATUS"
    assert result["clarifyAttempts"] == 0


# --- UNSUPPORTED: fixed honest response, thread stays alive ---


def test_unsupported_request_gets_a_fixed_honest_response():
    config = _config("unsupported")
    result = v2_agent_graph.invoke(
        {"userMessage": "Can I change my shipping address?", "threadId": _thread_id_for(config)},
        config=config,
    )

    assert result["status"] == "UNSUPPORTED"
    assert "__interrupt__" not in result
    assert result["uiState"]["uiMode"] == "welcome"
    assert "not able to help with that here" in result["uiState"]["assistantMessage"]


def test_thread_recovers_after_an_unsupported_turn():
    config = _config("unsupported-recover")
    v2_agent_graph.invoke(
        {"userMessage": "Can I change my shipping address?", "threadId": _thread_id_for(config)},
        config=config,
    )

    result = v2_agent_graph.invoke({"userMessage": "Where is order U-1002?"}, config=config)

    assert result["activeCapability"] == "ORDER_STATUS"
    assert result["status"] == "FINAL"


def test_unsupported_via_http_endpoint():
    response = client.post(
        "/v2/agent/chat", json={"message": "Can I update my payment method?"}
    ).json()

    assert response["status"] == "UNSUPPORTED"
    assert response["capability"] == "UNSUPPORTED"


# --- loop-safety sanity: CLARIFY's cap is independent of MAX_LOOP_ITERATIONS ---


def test_clarify_cap_is_reached_well_before_the_general_iteration_cap():
    config = _config("clarify-cap-vs-iterations")
    r1 = v2_agent_graph.invoke({"userMessage": "help", "threadId": _thread_id_for(config)}, config=config)
    r2 = v2_agent_graph.invoke(Command(resume={"customerReply": "stuff"}), config=config)
    result = v2_agent_graph.invoke(Command(resume={"customerReply": "not sure"}), config=config)

    assert result["loopIteration"] < loop_safety.MAX_LOOP_ITERATIONS
