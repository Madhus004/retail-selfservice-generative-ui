# agent/test_v3_cancellation.py
#
# Phase 3 — CANCELLATION, V3's first sensitive-action capability. Proves
# the full confirmation/idempotency cycle (v3/confirmation.py,
# v3/idempotency.py, both SQLite-backed) against the new messages-list
# graph: propose -> confirm -> execute, decline, dry-run/validation
# failure, the free-text-is-never-authorization guard, idempotency replay,
# and — the specific risk this split exists to close off — that
# tools.submit_order_cancellation is invoked ZERO times before a valid
# Confirm and EXACTLY ONCE after one.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import itertools
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from main import app
from v3 import idempotency
from v3.graph import build_graph, execute_confirmed_action_node, execute_tool_node, request_confirmation_node
import v3.tools.cancellation_tools as cancellation_tools_module

client = TestClient(app)

_thread_counter = itertools.count()
_run_counter = itertools.count()
# Computed once per process — see test_v3_order_status.py's _RUN_SUFFIX
# comment: main.app's v3_agent_graph is backed by a real, persistent
# SQLite checkpointer, so a purely sequential thread_id would collide
# across separate pytest invocations of this file.
_RUN_SUFFIX = uuid.uuid4().hex[:8]


def _new_thread_id() -> str:
    return f"cancellation-test-{_RUN_SUFFIX}-{next(_thread_counter)}"


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


def _reach_confirmation_pending(graph, order_number: str, thread_id: str):
    """
    Drives the deterministic flow up to a real CONFIRM_ACTION interrupt.
    "Cancel order <N>" already names the order, so the fallback skips
    past the order-selection ask — but still asks for item selection
    whenever the order has more than one cancellable item, so this walks
    through both possible ASK_CUSTOMER stages.
    """

    result = graph.invoke(
        {"messages": [HumanMessage(content=f"Cancel order {order_number}")], "threadId": thread_id},
        config=_config(thread_id),
    )
    interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ORDER_SELECTED":
        result = graph.invoke(
            Command(resume={"type": "ORDER_SELECTED", "payload": {"orderNumber": order_number}}),
            config=_config(thread_id),
        )
        interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ITEM_SELECTED":
        item_candidates = interrupt_value["offeredCandidates"]["items"]
        selections = [
            {"orderLineId": line_id, "quantity": info["maxQuantity"]} for line_id, info in item_candidates.items()
        ]
        result = graph.invoke(
            Command(resume={"type": "ITEM_SELECTED", "payload": {"selections": selections}}),
            config=_config(thread_id),
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    return interrupt_value["actionId"], interrupt_value["actionType"]


# --- canvasData carries real data for the frontend to render against ---


def test_item_selection_ask_carries_eligible_orders_in_canvas_data(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="Cancel order U-1004")], "threadId": thread_id},
        config=_config(thread_id),
    )
    interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["expectedInteractionType"] == "ITEM_SELECTED"
    eligible_orders = interrupt_value["uiState"]["canvasData"]["eligibleOrders"]
    assert any(o["orderNumber"] == "U-1004" for o in eligible_orders)


def test_confirmation_pending_carries_preview_and_eligible_orders_in_canvas_data(graph):
    thread_id = _new_thread_id()
    _reach_confirmation_pending(graph, "U-1005", thread_id)

    snapshot = graph.get_state(_config(thread_id))
    interrupt_value = snapshot.interrupts[0].value

    assert interrupt_value["uiState"]["canvasData"]["preview"]["orderNumber"] == "U-1005"
    assert any(o["orderNumber"] == "U-1005" for o in interrupt_value["uiState"]["canvasData"]["eligibleOrders"])


# --- capability boundary, structural ---


def test_cancellation_is_bound_to_both_its_tools():
    from v3.capabilities.registry import get_capability

    capability = get_capability("CANCELLATION")
    tool_names = {t.name for t in capability.tools}

    assert tool_names == {"get_cancellation_eligible_orders_tool", "submit_order_cancellation_tool"}


def test_cancellation_declares_submit_as_its_sole_sensitive_tool():
    from v3.capabilities.registry import get_capability

    assert get_capability("CANCELLATION").sensitive_tool_names == ["submit_order_cancellation_tool"]


# --- full cycle ---


def test_full_propose_confirm_execute_cycle(graph):
    thread_id = _new_thread_id()
    # U-1005 has a single cancellable item — auto-selected, no ITEM_SELECTED ask.
    action_id, action_type = _reach_confirmation_pending(graph, "U-1005", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "ConfirmationCard"
    assert result["a2uiOrigin"] == "MANDATORY_DETERMINISTIC"
    assert result["pendingAction"]["consumed"] is True
    assert result["pendingAction"]["executed"] is True

    exec_record = result["toolCallLog"][-1]
    assert exec_record["toolName"] == "submit_order_cancellation_tool"
    assert exec_record["resultSummary"]["orderNumber"] == "U-1005"
    assert idempotency.has_executed(action_id)
    assert "done" in result["uiState"]["assistantMessage"].lower()


def test_full_cycle_with_multi_item_order_asks_for_items_first(graph):
    thread_id = _new_thread_id()
    # U-1004 has two cancellable items — must ask ITEM_SELECTED.
    action_id, action_type = _reach_confirmation_pending(graph, "U-1004", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["pendingAction"]["executed"] is True
    assert len(result["pendingAction"]["proposedPayload"]["line_selections"]) == 2


# --- declining ---


def test_declining_does_not_execute_and_clears_pending_action(graph):
    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1005", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["pendingAction"] is None
    assert not any(r["toolName"] == "submit_order_cancellation_tool" for r in result["toolCallLog"])
    assert not idempotency.has_executed(action_id)
    assert "won't cancel" in result["uiState"]["assistantMessage"].lower()


def test_declining_is_never_re_proposed_on_the_next_turn(graph):
    """
    The mandatory decline gate in agent_reason_node — added specifically
    so a decline is never left to the LLM's own (possibly forgetful)
    judgment — must fire deterministically regardless of API key.
    """

    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1005", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert "__interrupt__" not in result
    assert not any(r["toolName"] == "submit_order_cancellation_tool" for r in result["toolCallLog"])


# --- correction 1: free text is never authorization ---


def test_typed_yes_during_confirmation_never_executes(graph):
    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1005", thread_id)

    result = graph.invoke(
        Command(resume={"__confirmationReminder__": True, "customerMessage": "yes, go ahead and do it"}),
        config=_config(thread_id),
    )

    # Re-interrupted with the SAME pending action, still PENDING — never
    # treated as authorization.
    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    assert interrupt_value["actionId"] == action_id
    assert not idempotency.has_executed(action_id)

    # The same actionId can still be confirmed for real afterward.
    result2 = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )
    assert result2["status"] == "FINAL"
    assert idempotency.has_executed(action_id)


def test_typed_yes_via_http_endpoint_returns_interrupted_confirm_status():
    thread_id = _new_thread_id()
    resp1 = client.post("/v3/agent/chat", json={"message": "Cancel order U-1005", "threadId": thread_id}).json()

    # U-1005 is auto-selected/auto-single-item, so this reaches CONFIRM_ACTION directly.
    assert resp1["status"] == "INTERRUPTED_CONFIRM"

    resp2 = client.post("/v3/agent/chat", json={"threadId": thread_id, "message": "yes please"}).json()

    assert resp2["status"] == "INTERRUPTED_CONFIRM"
    assert resp2["uiState"]["a2ui"][0]["props"]["phase"] == "PENDING"


# --- validation/dry-run failure ---


def test_invalid_quantity_never_creates_a_pending_action():
    # Directly exercise request_confirmation_node's validation path with a
    # quantity that exceeds what's actually cancellable — the underlying
    # tool call itself should raise, never reaching a confirmation screen.
    state = {
        "activeCapability": "CANCELLATION",
        "threadId": "dry-run-fail-direct",
        "loopIteration": 0,
        "toolCallLog": [],
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
    assert result["toolCallLog"][-1]["error"]


# --- defense in depth ---


def test_execute_tool_refuses_to_call_a_sensitive_tool_directly():
    from langchain_core.messages import AIMessage

    state = {
        "activeCapability": "CANCELLATION",
        "_decision": {
            "action": "CALL_TOOL",
            "toolName": "submit_order_cancellation_tool",
            "toolArgs": {"order_number": "U-1004", "line_selections": [], "reason": "x"},
        },
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_test",
                        "name": "submit_order_cancellation_tool",
                        "args": {"order_number": "U-1004", "line_selections": [], "reason": "x"},
                    }
                ],
            )
        ],
        "toolCallLog": [],
        "loopIteration": 0,
    }

    result = execute_tool_node(state)

    assert "sensitive" in result["toolCallLog"][-1]["error"].lower()


# --- idempotency replay (unit-level) ---


def test_idempotency_replay_returns_cached_result_without_re_executing():
    from v3 import confirmation as confirmation_module

    pending = confirmation_module.create_pending_action(
        "replay-test-action-id",
        "SUBMIT_CANCELLATION",
        "CANCELLATION",
        {"order_number": "U-1004", "line_selections": [], "reason": "x"},
        eligibility_checked=True,
    )
    idempotency.record_executed(pending["actionId"], {"orderNumber": "U-1004", "resultingOrderStatus": "Cancelled"})

    state = {
        "activeCapability": "CANCELLATION",
        "pendingAction": pending,
        "_confirmationReply": {"actionId": pending["actionId"], "actionType": "SUBMIT_CANCELLATION", "accepted": True},
        "messages": [],
        "toolCallLog": [],
    }

    result = execute_confirmed_action_node(state)

    assert result["_mandatoryUi"][0]["type"] == "ConfirmationCard"
    assert result["_decision"]["action"] == "FINISH"
    assert "already submitted" in result["_decision"]["message"].lower()
    # No new tool execution happened — toolCallLog was never appended to.
    assert result["toolCallLog"] == []


# --- premature-execution proof: zero calls before Confirm, exactly one after ---


def test_submit_order_cancellation_zero_before_one_after_confirm(graph, monkeypatch):
    spy = MagicMock(wraps=cancellation_tools_module.submit_order_cancellation)
    monkeypatch.setattr(cancellation_tools_module, "submit_order_cancellation", spy)

    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1004", thread_id)

    # Nothing before Confirm — not the order/item ASK_CUSTOMER stages, not
    # the PENDING preview screen itself — ever called the real function.
    assert spy.call_count == 0

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 1


def test_declining_never_invokes_the_real_function(graph, monkeypatch):
    spy = MagicMock(wraps=cancellation_tools_module.submit_order_cancellation)
    monkeypatch.setattr(cancellation_tools_module, "submit_order_cancellation", spy)

    thread_id = _new_thread_id()
    action_id, action_type = _reach_confirmation_pending(graph, "U-1004", thread_id)

    result = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 0


# --- HTTP endpoint shape ---


def test_v3_agent_chat_endpoint_full_cycle():
    thread_id = _new_thread_id()
    resp1 = client.post("/v3/agent/chat", json={"message": "Cancel order U-1005", "threadId": thread_id}).json()

    assert resp1["status"] == "INTERRUPTED_CONFIRM"
    assert resp1["uiState"]["uiMode"] == "ConfirmationCard"

    action_id = resp1["uiState"]["a2ui"][0]["props"]["pending"]["actionId"]
    action_type = resp1["uiState"]["a2ui"][0]["props"]["pending"]["actionType"]

    resp2 = client.post(
        "/v3/agent/chat",
        json={
            "threadId": thread_id,
            "resume": {"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}},
        },
    ).json()

    assert resp2["status"] == "FINAL"
    assert resp2["capability"] == "CANCELLATION"
