# agent/test_v3_order_status.py
#
# Phase 1 — ORDER_STATUS, V3's first real capability. OPENAI_API_KEY is
# cleared for every test so these exercise the deterministic path — fast,
# free, reproducible, and precisely assertable, exactly the property that
# caught a real bug while this file was being written (see
# test_a_later_message_naming_a_different_order_is_never_answered_from_a_stale_cache
# below): _deterministic_order_status originally treated "any cached
# get_order_status_tool result exists" as "ready to answer," without
# checking WHICH order that cached result was for. A second order-status
# question in the same thread, with no capability switch in between (so
# toolCallLog was never reset), would have silently answered from the
# first order's stale cache — the exact class of bug this whole rebuild
# exists to close off, just reached through a different mechanism than the
# one V2 had. Fixed in graph.py by checking the cached result's own
# orderNumber against the currently-resolved one before trusting it.

import itertools
import uuid

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from main import app
from v3.graph import build_graph

client = TestClient(app)

_thread_counter = itertools.count()
_run_counter = itertools.count()
# Computed once per process — main.app's v3_agent_graph uses a REAL,
# persistent SQLite checkpointer (agent/v3/data/app.db), so a purely
# sequential thread_id ("order-status-test-3") would collide with the
# SAME string from a PRIOR pytest invocation of this file, silently
# resuming a stale, possibly mid-flow thread instead of starting fresh.
_RUN_SUFFIX = uuid.uuid4().hex[:8]


def _new_thread_id() -> str:
    return f"order-status-test-{_RUN_SUFFIX}-{next(_thread_counter)}"


def _config(thread_id: str):
    return {"configurable": {"thread_id": thread_id, "run_id": f"test-run-{next(_run_counter)}"}}


@pytest.fixture()
def graph():
    return build_graph().compile(checkpointer=InMemorySaver())


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- known order number: direct path, no ask ---


def test_known_order_number_calls_status_tool_directly_and_finishes(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1002?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "OrderSummaryCard"
    assert [r["toolName"] for r in result["toolCallLog"]] == ["get_order_status_tool"]
    assert result["toolCallLog"][0]["argsSummary"] == {"order_number": "U-1002"}


def test_a_nonexistent_order_number_surfaces_as_a_tool_error_not_a_crash(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-9999?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["toolCallLog"][-1]["error"]
    assert "U-9999" in result["uiState"]["assistantMessage"]
    # Never silently retried into the loop-safety escalation net — a
    # failed lookup for one order is a definitive, first-choice answer.
    assert len(result["toolCallLog"]) == 1


# --- multiple orders: real interrupt, structured resume ---


def test_multiple_orders_asks_which_one_then_resumes_to_the_right_answer(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is my order?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "ORDER_SELECTED"
    order_numbers = interrupt_value["offeredCandidates"]["orderNumbers"]
    assert len(order_numbers) > 1

    picked = order_numbers[2]
    result2 = graph.invoke(
        Command(resume={"type": "ORDER_SELECTED", "payload": {"orderNumber": picked}}),
        config=_config(thread_id),
    )

    assert result2["status"] == "FINAL"
    assert result2["toolCallLog"][-1]["toolName"] == "get_order_status_tool"
    assert result2["toolCallLog"][-1]["argsSummary"] == {"order_number": picked}


def test_a_selection_outside_the_offered_set_is_rejected_not_forwarded(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is my order?")], "threadId": thread_id},
        config=_config(thread_id),
    )
    interrupt_value = result["__interrupt__"][0].value
    real_orders = set(interrupt_value["offeredCandidates"]["orderNumbers"])
    assert "U-0000" not in real_orders

    result2 = graph.invoke(
        Command(resume={"type": "ORDER_SELECTED", "payload": {"orderNumber": "U-0000"}}),
        config=_config(thread_id),
    )

    # Rejected and re-asked — never silently accepted, never crashed.
    assert "__interrupt__" in result2
    interrupt_value2 = result2["__interrupt__"][0].value
    assert interrupt_value2["interruptType"] == "ASK_CUSTOMER"
    assert "doesn't match" in interrupt_value2["message"]


# --- the exact regression this file's own writing caught ---


def test_a_later_message_naming_a_different_order_is_never_answered_from_a_stale_cache(graph):
    """
    Two order-status questions in the same thread, same capability (no
    switch, so toolCallLog is never reset) — the second must be answered
    from a FRESH get_order_status_tool(U-1004) call, never from the first
    call's cached U-1002 result. toolCallLog being an ordered list (not a
    dict keyed by tool name) means BOTH calls survive intact; this test
    additionally proves the READING side respects which one is actually
    relevant right now.
    """

    thread_id = _new_thread_id()
    r1 = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1002?")], "threadId": thread_id},
        config=_config(thread_id),
    )
    assert r1["status"] == "FINAL"

    r2 = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1004?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert r2["status"] == "FINAL"
    tool_calls = [(r["toolName"], r["argsSummary"]) for r in r2["toolCallLog"]]
    assert ("get_order_status_tool", {"order_number": "U-1002"}) in tool_calls  # first call preserved
    assert ("get_order_status_tool", {"order_number": "U-1004"}) in tool_calls  # second call actually happened
    assert r2["toolCallLog"][-1]["argsSummary"] == {"order_number": "U-1004"}


# --- HTTP endpoint shape ---


def test_v3_agent_chat_endpoint_known_order():
    thread_id = _new_thread_id()
    response = client.post(
        "/v3/agent/chat", json={"message": "Where is order U-1002?", "threadId": thread_id}
    ).json()

    assert response["status"] == "FINAL"
    assert response["capability"] == "ORDER_STATUS"
    assert response["uiState"]["uiMode"] == "OrderSummaryCard"


def test_v3_agent_chat_endpoint_multi_order_resume():
    thread_id = _new_thread_id()
    resp1 = client.post("/v3/agent/chat", json={"message": "Where is my order?", "threadId": thread_id}).json()
    assert resp1["status"] == "INTERRUPTED_ASK"

    orders = resp1["uiState"]["canvasData"]["orders"]
    picked = orders[0]["orderNumber"]

    resp2 = client.post(
        "/v3/agent/chat",
        json={"threadId": thread_id, "resume": {"type": "ORDER_SELECTED", "payload": {"orderNumber": picked}}},
    ).json()

    assert resp2["status"] == "FINAL"
    assert resp2["uiState"]["canvasData"]["selectedOrder"]["order"]["orderNumber"] == picked
