# agent/test_v2_conversation_memory.py
#
# Conversation memory (2026-08 fix) — conversationSummary existed in
# AgentStateV2 since Phase 0 but was never populated or read anywhere,
# which meant the classifier and agent_reason's LLM calls only ever saw
# activeCapability/toolResults/a handful of scratch fields, never what was
# actually said in earlier turns. This covers: the append/cap/dedupe
# behavior of _record_conversation_turn, _build_messages including prior
# turns, and an end-to-end multi-turn run actually accumulating both sides
# of the exchange.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import itertools

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from v2 import graph as graph_module
from v2.capabilities.registry import get_capability
from v2.graph import (
    _build_messages,
    _MAX_CONVERSATION_TURNS,
    _record_conversation_turn,
    v2_agent_graph,
)

_thread_counter = itertools.count()


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _config():
    return {"configurable": {"thread_id": f"conv-memory-test-{next(_thread_counter)}"}}


# --- _record_conversation_turn ---


def test_record_conversation_turn_appends_role_and_content():
    state = {}
    _record_conversation_turn(state, "user", "Where is my order?")
    _record_conversation_turn(state, "assistant", "Which order would you like to check?")

    assert state["conversationSummary"] == [
        {"role": "user", "content": "Where is my order?"},
        {"role": "assistant", "content": "Which order would you like to check?"},
    ]


def test_record_conversation_turn_skips_empty_content():
    state = {}
    _record_conversation_turn(state, "assistant", "")
    _record_conversation_turn(state, "assistant", None)

    assert state.get("conversationSummary", []) == []


def test_record_conversation_turn_is_idempotent_against_immediate_duplicate():
    state = {}
    _record_conversation_turn(state, "assistant", "Why are you returning this?")
    _record_conversation_turn(state, "assistant", "Why are you returning this?")

    assert len(state["conversationSummary"]) == 1


def test_record_conversation_turn_caps_at_max_and_drops_oldest():
    state = {}
    for i in range(_MAX_CONVERSATION_TURNS + 5):
        _record_conversation_turn(state, "user", f"message {i}")

    turns = state["conversationSummary"]
    assert len(turns) == _MAX_CONVERSATION_TURNS
    # Oldest entries were dropped — the tail is preserved.
    assert turns[-1]["content"] == f"message {_MAX_CONVERSATION_TURNS + 4}"
    assert turns[0]["content"] == "message 5"


# --- _build_messages includes prior turns ---


def test_build_messages_includes_prior_conversation_turns_before_the_current_one():
    state = {
        "userMessage": "Actually, why is it late?",
        "toolResults": {},
        "conversationSummary": [
            {"role": "user", "content": "Where is order U-1002?"},
            {"role": "assistant", "content": "It's on its way, arriving soon."},
        ],
    }
    capability = get_capability("ORDER_STATUS")

    messages = _build_messages(state, capability)

    # System message, then the two prior turns as real message history,
    # then the current turn's HumanMessage last.
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "Where is order U-1002?"
    assert isinstance(messages[2], AIMessage)
    assert messages[2].content == "It's on its way, arriving soon."
    assert isinstance(messages[-1], HumanMessage)
    assert "Actually, why is it late?" in messages[-1].content


def test_build_messages_last_known_order_hint_only_fires_for_a_real_cross_capability_switch():
    """
    Regression: the "customer was just looking at order X" hint text is
    meant only for a genuine cross-capability carry-over (plan walkthrough
    F). A same-capability capabilityTransition (from == to — e.g. the
    classifier flagging isCapabilitySwitch=True for a same-capability
    message like the "Track a different order" chip) must never trigger
    it, since that hint told the model the OLD order was "likely still
    relevant" right when the customer was asking to move on from it.
    """

    capability = get_capability("ORDER_STATUS")

    same_capability_state = {
        "userMessage": "Track a different order",
        "toolResults": {},
        "capabilityTransition": {"from": "ORDER_STATUS", "to": "ORDER_STATUS"},
        "lastKnownOrderNumber": "U-1003",
    }
    messages = _build_messages(same_capability_state, capability)
    assert "U-1003" not in messages[-1].content

    cross_capability_state = {
        "userMessage": "It says delivered but I never got it.",
        "toolResults": {},
        "capabilityTransition": {"from": "ORDER_STATUS", "to": "WRONG_DELIVERY"},
        "lastKnownOrderNumber": "U-1003",
    }
    messages = _build_messages(cross_capability_state, capability)
    assert "U-1003" in messages[-1].content


# --- end-to-end: both sides of a real multi-turn exchange get recorded ---


def test_multi_turn_order_status_accumulates_both_sides_of_the_conversation():
    config = _config()
    result = v2_agent_graph.invoke({"userMessage": "Where is my order?"}, config=config)

    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": "U-1002"},
            }
        ),
        config=config,
    )

    assert result["status"] == "FINAL"
    turns = result["conversationSummary"]
    roles = [t["role"] for t in turns]

    assert roles[0] == "user"
    assert turns[0]["content"] == "Where is my order?"
    assert "assistant" in roles
    # The final answer text is the same text shown to the customer.
    assert turns[-1] == {"role": "assistant", "content": result["uiState"]["assistantMessage"]}


def test_classifier_receives_prior_turns_on_a_second_message(monkeypatch):
    captured_contexts = []
    real_classify = graph_module.classify

    def spy_classify(message, context=None):
        captured_contexts.append(context)
        return real_classify(message, context)

    monkeypatch.setattr(graph_module, "classify", spy_classify)

    config = _config()
    result = v2_agent_graph.invoke({"userMessage": "Where is order U-1002?"}, config=config)
    assert result["status"] == "FINAL"

    v2_agent_graph.invoke({"userMessage": "Why is it late?"}, config=config)

    assert len(captured_contexts) == 2
    assert captured_contexts[0].recentTurnsSummary == []  # nothing before the first turn
    assert captured_contexts[1].recentTurnsSummary != []  # the first exchange is now visible
