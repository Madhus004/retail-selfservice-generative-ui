# agent/test_v3_returns.py
#
# Phase 4 — RETURNS, V3's second sensitive-action capability. The 7
# validate_confirmation checks and general __confirmationReminder__/
# idempotency mechanics are capability-agnostic and already fully covered
# by test_v3_cancellation.py; this file covers what's genuinely new here:
# the get_return_eligible_items/create_return deterministic functions
# (404/409/400 + refund-estimate math), the multi-stage ask flow (order,
# item, reason, method), and the full propose/confirm/execute/decline
# cycle for this capability specifically.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import itertools
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from main import app
from v3 import idempotency
from v3.graph import build_graph
import v3.tools.returns_tools as returns_tools_module
from v3.tools.returns_tools import create_return, get_return_eligible_items

client = TestClient(app)

_thread_counter = itertools.count()
_run_counter = itertools.count()
# Computed once per process — main.app's v3_agent_graph uses a REAL,
# persistent SQLite checkpointer (agent/v3/data/app.db), so a purely
# sequential thread_id ("returns-test-3") would collide with the SAME
# string from a PRIOR pytest invocation of this file, silently resuming a
# stale, possibly mid-flow thread (e.g. one paused at CONFIRM_ACTION)
# instead of starting a genuinely fresh conversation. Confirmed as the
# root cause of a flaky failure while writing this file's HTTP endpoint
# test — the real-LLM path reached CONFIRM_ACTION on "turn 1" because that
# thread_id string had already been driven there by an earlier run.
_RUN_SUFFIX = uuid.uuid4().hex[:8]


def _new_thread_id() -> str:
    return f"returns-test-{_RUN_SUFFIX}-{next(_thread_counter)}"


def _config(thread_id: str):
    return {"configurable": {"thread_id": thread_id, "run_id": f"test-run-{next(_run_counter)}"}}


@pytest.fixture()
def graph():
    return build_graph().compile(checkpointer=InMemorySaver())


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def clear_idempotency_store():
    idempotency.clear_all()
    yield
    idempotency.clear_all()


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


def test_asks_which_order_when_none_named_and_multiple_exist(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="I want to return something.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "ORDER_SELECTED"
    assert interrupt_value["uiState"]["uiMode"] == "OrderListPicker"
    offered = interrupt_value["offeredCandidates"]["orderNumbers"]
    assert "U-1001" in offered
    assert "U-1002" in offered
    # get_return_eligible_orders_tool only ever offers return-eligible
    # orders — U-1003/U-1004/U-1005 are in-transit/not-yet-shipped.
    assert "U-1003" not in offered
    assert "U-1004" not in offered
    assert "U-1005" not in offered
    # The order list itself is renderable data, not just candidate ids —
    # the frontend has nothing to show an OrderListPicker against otherwise.
    canvas_orders = interrupt_value["uiState"]["canvasData"]["returnEligibleOrders"]
    assert {o["orderNumber"] for o in canvas_orders} == {"U-1001", "U-1002"}


def test_item_selection_ask_carries_return_eligibility_in_canvas_data(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="I want to return order U-1001.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["expectedInteractionType"] == "ITEM_SELECTED"
    eligibility = interrupt_value["uiState"]["canvasData"]["returnEligibility"]
    assert eligibility["orderNumber"] == "U-1001"
    assert len(eligibility["items"]) == 2


def test_reason_ask_carries_the_fixed_reason_options_in_canvas_data(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="I want to return order U-1002.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["expectedInteractionType"] == "REASON_SELECTED"
    assert interrupt_value["uiState"]["canvasData"]["returnReasonOptions"] == [
        "Wrong size/fit",
        "Changed my mind",
        "Defective/damaged",
        "Other",
    ]


def test_tampered_order_selection_outside_the_offered_set_is_rejected(graph):
    thread_id = _new_thread_id()
    graph.invoke(
        {"messages": [HumanMessage(content="I want to return something.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    result = graph.invoke(
        Command(resume={"type": "ORDER_SELECTED", "payload": {"orderNumber": "U-9999"}}),
        config=_config(thread_id),
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert "doesn't match" in interrupt_value["message"].lower()


def _cancellation_eligible_orders_record():
    return {
        "callId": "1",
        "toolName": "get_cancellation_eligible_orders_tool",
        "argsSummary": {},
        "resultSummary": {"orders": []},
        "isSensitive": False,
        "startedAt": "",
        "finishedAt": "",
        "error": None,
    }


def _return_eligible_orders_record():
    return {
        "callId": "2",
        "toolName": "get_return_eligible_orders_tool",
        "argsSummary": {},
        "resultSummary": {
            "orders": [
                {"orderNumber": "U-1001", "orderStatus": "Delivered", "items": []},
                {"orderNumber": "U-1002", "orderStatus": "Delivered", "items": []},
            ]
        },
        "isSensitive": False,
        "startedAt": "",
        "finishedAt": "",
        "error": None,
    }


def test_returns_stage_never_trusts_a_resolved_order_not_in_the_fetched_eligible_list():
    """
    Regression test for a real bug found via manual testing: cancelling
    U-1004 and then, in the same thread, asking to return something
    without naming an order silently treated U-1004 as already resolved
    (via the classifier's own inference from conversation context, or a
    carried-over lastKnownOrderNumber — either way, a value
    _resolve_order_number can return that was never actually validated)
    — skipping the order-selection ask entirely, even though U-1004 isn't
    return-eligible. The turn reached FINAL with no real interrupt behind
    the order cards it displayed, so clicking one afterward just replayed
    the same stale response. RETURNS must only trust a resolved order
    number once confirmed against its OWN fetched eligible-orders list.
    """

    from v3.graph import _returns_stage

    state = {
        "messages": [],
        "activeCapability": "RETURNS",
        "_classification": {"orderNumber": "U-1004"},
        "toolCallLog": [_return_eligible_orders_record()],
    }

    assert _returns_stage(state) == "WAITING_FOR_ORDER_SELECTION"


def test_deterministic_returns_asks_instead_of_silently_resolving_a_mismatched_order():
    from v3.graph import _deterministic_returns

    state = {
        "messages": [],
        "activeCapability": "RETURNS",
        "_classification": {"orderNumber": "U-1004"},
        "toolCallLog": [_return_eligible_orders_record()],
    }

    decision = _deterministic_returns(state)

    assert decision["action"] == "ASK_CUSTOMER"
    assert decision["interactionType"] == "ORDER_SELECTED"


def test_returns_stage_trusts_a_resolved_order_once_it_matches_the_fetched_list():
    from v3.graph import _returns_stage

    state = {
        "messages": [],
        "activeCapability": "RETURNS",
        "_classification": {"orderNumber": "U-1002"},
        "toolCallLog": [_return_eligible_orders_record()],
    }

    # U-1002 IS among the fetched eligible orders — safe to trust and move on.
    assert _returns_stage(state) == "NEED_ELIGIBILITY_CHECK"


def test_returns_stage_trusts_a_resolved_order_before_anything_is_fetched_yet():
    """
    The safe fast path: nothing fetched yet this turn, so a resolved order
    number goes straight to the self-validating get_return_eligible_items_tool
    call rather than requiring a full order-list fetch first.
    """

    from v3.graph import _returns_stage

    state = {
        "messages": [],
        "activeCapability": "RETURNS",
        "_classification": {"orderNumber": "U-1002"},
        "toolCallLog": [],
    }

    assert _returns_stage(state) == "NEED_ELIGIBILITY_CHECK"


def test_returns_recovers_after_an_ineligible_order_instead_of_getting_stuck(graph):
    """
    Regression test for a real bug found via live manual testing: asking
    ORDER_STATUS about U-1003 (not yet delivered), then switching to
    RETURNS with no order named, carried U-1003 over as the "resolved"
    order via lastKnownOrderNumber. RETURNS correctly reported it as
    ineligible and finished. But asking about returns AGAIN afterward
    (still no order named) should offer the real return-eligible orders
    list (U-1001/U-1002) — instead it stayed stuck reporting the same
    stale ineligibility forever, because _returns_stage/_deterministic_returns
    read "the most recent get_return_eligible_items_tool call in the whole
    log" rather than the eligibility for whichever order is actually being
    discussed this turn. A fresh get_return_eligible_orders_tool fetch was
    never even considered once that one ineligible record existed.
    """

    thread_id = _new_thread_id()

    order_status_result = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1003?")], "threadId": thread_id},
        config=_config(thread_id),
    )
    assert order_status_result["status"] == "FINAL"

    first_returns_attempt = graph.invoke(
        {"messages": [HumanMessage(content="I'd like to return something.")], "threadId": thread_id},
        config=_config(thread_id),
    )
    assert first_returns_attempt["status"] == "FINAL"
    assert "hasn't been delivered" in first_returns_attempt["uiState"]["assistantMessage"]

    second_returns_attempt = graph.invoke(
        {"messages": [HumanMessage(content="I still want to return something.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert "__interrupt__" in second_returns_attempt
    interrupt_value = second_returns_attempt["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "ORDER_SELECTED"
    offered = interrupt_value["offeredCandidates"]["orderNumbers"]
    assert {"U-1001", "U-1002"} <= set(offered)


def test_returns_never_reuses_a_stale_item_selection_left_over_from_cancellation(graph):
    """
    Regression test for a real bug found via manual testing (live, with a
    real LLM): completing a CANCELLATION on U-1004 via an explicit
    ITEM_SELECTED resume (picking one of its two items) sets
    state["_selectedLineItems"]. Pivoting to RETURNS afterward and
    selecting a DIFFERENT multi-item order (U-1001) then skipped RETURNS'
    own item-selection ask entirely and jumped straight to the reason
    prompt — because enforce_capability_switch_node never reset
    _selectedLineItems/_selectedReason/_selectedReturnMethod on a switch,
    so RETURNS' "has an item already been selected?" check saw CANCELLATION's
    leftover (and irrelevant) selection and treated it as already answered.
    """

    thread_id = _new_thread_id()

    cancel_result = graph.invoke(
        {"messages": [HumanMessage(content="Cancel order U-1004")], "threadId": thread_id},
        config=_config(thread_id),
    )
    interrupt_value = cancel_result["__interrupt__"][0].value
    assert interrupt_value["expectedInteractionType"] == "ITEM_SELECTED"

    confirm_pending = graph.invoke(
        Command(
            resume={"type": "ITEM_SELECTED", "payload": {"selections": [{"orderLineId": "OL-1004-1", "quantity": 1}]}}
        ),
        config=_config(thread_id),
    )
    confirm_interrupt = confirm_pending["__interrupt__"][0].value
    assert confirm_interrupt["interruptType"] == "CONFIRM_ACTION"

    cancellation_final = graph.invoke(
        Command(
            resume={
                "confirmation": {
                    "actionId": confirm_interrupt["actionId"],
                    "actionType": confirm_interrupt["actionType"],
                    "accepted": True,
                }
            }
        ),
        config=_config(thread_id),
    )
    assert cancellation_final["status"] == "FINAL"
    assert cancellation_final["_selectedLineItems"] is not None

    # Pivot to RETURNS, name a DIFFERENT multi-item order directly.
    returns_result = graph.invoke(
        {"messages": [HumanMessage(content="I want to return order U-1001.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert "__interrupt__" in returns_result
    returns_interrupt = returns_result["__interrupt__"][0].value
    assert returns_interrupt["interruptType"] == "ASK_CUSTOMER"
    assert returns_interrupt["expectedInteractionType"] == "ITEM_SELECTED"


def test_selecting_an_offered_order_proceeds_to_the_reason_stage(graph):
    """
    U-1002 has only one returnable item, so item selection auto-skips —
    but a reason is always asked, so the very next stage after a valid
    order selection is REASON_SELECTED, not straight to confirmation.
    """

    thread_id = _new_thread_id()
    graph.invoke(
        {"messages": [HumanMessage(content="I want to return something.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    result = graph.invoke(
        Command(resume={"type": "ORDER_SELECTED", "payload": {"orderNumber": "U-1002"}}),
        config=_config(thread_id),
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "REASON_SELECTED"
    assert interrupt_value["uiState"]["uiMode"] == "ReturnReasonPrompt"


# --- ineligible order finishes cleanly, no confirmation ever offered ---


def test_ineligible_order_named_up_front_finishes_without_a_pending_action(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="I want to return order U-1003.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert "__interrupt__" not in result
    assert result["status"] == "FINAL"
    assert result.get("pendingAction") is None
    assert "hasn't been delivered" in result["uiState"]["assistantMessage"]


# --- full cycle ---


def _reach_confirmation_pending(graph, order_number: str, thread_id: str):
    """
    Drives the deterministic flow up to a real CONFIRM_ACTION interrupt,
    walking through whichever ASK_CUSTOMER stages are actually required
    (item selection when there's more than one returnable item, reason
    always, method when more than one is available).
    """

    result = graph.invoke(
        {"messages": [HumanMessage(content=f"I want to return order {order_number}.")], "threadId": thread_id},
        config=_config(thread_id),
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

        result = graph.invoke(
            Command(resume={"type": interaction_type, "payload": payload}),
            config=_config(thread_id),
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    return interrupt_value["actionId"], interrupt_value["actionType"]


def test_full_propose_confirm_execute_cycle(graph):
    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1002", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "ConfirmationCard"
    assert result["a2uiOrigin"] == "MANDATORY_DETERMINISTIC"
    assert result["pendingAction"]["executed"] is True

    exec_record = result["toolCallLog"][-1]
    assert exec_record["toolName"] == "create_return_tool"
    assert exec_record["resultSummary"]["orderNumber"] == "U-1002"
    assert exec_record["resultSummary"]["refundEstimate"] == 79.22
    assert idempotency.has_executed(action_id)


def test_declining_does_not_submit_a_return(graph):
    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1002", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["pendingAction"] is None
    assert not any(r["toolName"] == "create_return_tool" for r in result["toolCallLog"])
    assert not idempotency.has_executed(action_id)
    assert "won't return" in result["uiState"]["assistantMessage"].lower()


def test_typed_yes_during_confirmation_never_submits_a_return(graph):
    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1002", thread_id)

    result = graph.invoke(
        Command(resume={"__confirmationReminder__": True, "customerMessage": "yes go ahead"}),
        config=_config(thread_id),
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    assert interrupt_value["actionId"] == action_id
    assert not idempotency.has_executed(action_id)

    result2 = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )
    assert result2["status"] == "FINAL"
    assert idempotency.has_executed(action_id)


# --- premature-execution proof ---


def test_create_return_zero_before_one_after_confirm(graph, monkeypatch):
    spy = MagicMock(wraps=returns_tools_module.create_return)
    monkeypatch.setattr(returns_tools_module, "create_return", spy)

    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1001", thread_id)

    assert spy.call_count == 0

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 1


# --- confirmation machinery reuse, spot-checked ---


def test_action_type_mismatch_is_rejected_for_this_capability_too():
    from v3 import confirmation as confirmation_module

    pending = confirmation_module.create_pending_action(
        "ret-action-1",
        "CREATE_RETURN",
        "RETURNS",
        {"order_number": "U-1002", "line_selections": [], "reason": "x"},
        eligibility_checked=True,
    )
    result = confirmation_module.validate_confirmation(
        pending, {"actionId": "ret-action-1", "actionType": "SUBMIT_CANCELLATION", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "ACTION_TYPE_MISMATCH"


def test_idempotency_replay_works_for_this_capability_too():
    from v3 import confirmation as confirmation_module

    pending = confirmation_module.create_pending_action(
        "ret-action-2",
        "CREATE_RETURN",
        "RETURNS",
        {"order_number": "U-1002", "line_selections": [], "reason": "x"},
        eligibility_checked=True,
    )
    idempotency.record_executed(pending["actionId"], {"returnId": "RTN-U1002-ABC123"})

    result = confirmation_module.validate_confirmation(
        pending, {"actionId": "ret-action-2", "actionType": "CREATE_RETURN", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "IDEMPOTENCY_REPLAY"


# --- capability boundary, structural ---


def test_returns_is_bound_to_all_three_tools_and_not_order_status():
    from v3.capabilities.registry import get_capability

    capability = get_capability("RETURNS")
    tool_names = {t.name for t in capability.tools}

    assert tool_names == {
        "get_return_eligible_orders_tool",
        "get_return_eligible_items_tool",
        "create_return_tool",
    }
    assert "get_order_status_tool" not in tool_names


# --- HTTP endpoint shape ---


def test_v3_agent_chat_endpoint_full_cycle():
    thread_id = _new_thread_id()
    resp1 = client.post(
        "/v3/agent/chat", json={"message": "I want to return order U-1002.", "threadId": thread_id}
    ).json()

    assert resp1["status"] == "INTERRUPTED_ASK"
    assert resp1["uiState"]["uiMode"] == "ReturnReasonPrompt"

    resp2 = client.post(
        "/v3/agent/chat",
        json={"threadId": thread_id, "resume": {"type": "REASON_SELECTED", "payload": {"reason": "Changed my mind"}}},
    ).json()

    # U-1002 supports two return methods (mail, in_store) — asked next.
    assert resp2["status"] == "INTERRUPTED_ASK"
    assert resp2["uiState"]["uiMode"] == "ReturnMethodPrompt"

    resp2b = client.post(
        "/v3/agent/chat",
        json={"threadId": thread_id, "resume": {"type": "RETURN_METHOD_SELECTED", "payload": {"method": "mail"}}},
    ).json()

    assert resp2b["status"] == "INTERRUPTED_CONFIRM"

    action_id = resp2b["uiState"]["a2ui"][0]["props"]["pending"]["actionId"]
    action_type = resp2b["uiState"]["a2ui"][0]["props"]["pending"]["actionType"]

    resp3 = client.post(
        "/v3/agent/chat",
        json={
            "threadId": thread_id,
            "resume": {"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}},
        },
    ).json()

    assert resp3["status"] == "FINAL"
    assert resp3["capability"] == "RETURNS"
