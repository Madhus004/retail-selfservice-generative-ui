# agent/test_v2_free_text_slot_fill.py
#
# Bounded free-text slot-filling at mandatory ask stages (2026-08 fix).
# Before this, free text arriving during WAITING_FOR_REASON/WAITING_FOR_METHOD
# got captured into userMessage but never read by anything — the deterministic
# gate only checks _selectedReason/_selectedReturnMethod, so a customer typing
# "it's too small" instead of clicking a button got the exact same question
# repeated verbatim. This covers: the bounded LLM call's own containment
# check (never trusts a match outside the offered candidates), the graph
# actually advancing past a mandatory stage when free text matches, and the
# corrective re-ask still firing when it doesn't.
#
# OPENAI_API_KEY is cleared for the "no key" tests and set to a fake value
# (with the underlying LLM class monkeypatched, never a real network call)
# for the slot-fill tests.

import itertools

import pytest
from langgraph.types import Command

from v2 import graph as graph_module
from v2.graph import _attempt_free_text_slot_fill, v2_agent_graph

_thread_counter = itertools.count()


def _config():
    return {"configurable": {"thread_id": f"slot-fill-test-{next(_thread_counter)}"}}


# --- _attempt_free_text_slot_fill: the bounded call itself ---


def test_no_api_key_returns_none_without_calling_anything(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = _attempt_free_text_slot_fill(["Wrong size/fit", "Changed my mind"], "it's too small")

    assert result is None


class _FakeSlotFillLLM:
    def __init__(self, matched_value):
        self._matched_value = matched_value

    def with_structured_output(self, _model):
        return self

    def invoke(self, _messages):
        return graph_module._SlotFillAttempt(matchedValue=self._matched_value)


def test_matched_value_within_candidates_is_returned(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_module, "ChatOpenAI", lambda **_kwargs: _FakeSlotFillLLM("Wrong size/fit")
    )

    result = _attempt_free_text_slot_fill(["Wrong size/fit", "Changed my mind"], "it's too small")

    assert result == "Wrong size/fit"


def test_matched_value_outside_candidates_is_never_trusted(monkeypatch):
    # Defense in depth (plan section 18a correction 3, applied to a
    # bounded-LLM result the same as any other unverified structured
    # input) — even if the model hallucinates something outside the
    # offered set, it must never be applied.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        graph_module, "ChatOpenAI", lambda **_kwargs: _FakeSlotFillLLM("Something not offered")
    )

    result = _attempt_free_text_slot_fill(["Wrong size/fit", "Changed my mind"], "it's too small")

    assert result is None


def test_no_confident_match_returns_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(graph_module, "ChatOpenAI", lambda **_kwargs: _FakeSlotFillLLM(None))

    result = _attempt_free_text_slot_fill(
        ["Wrong size/fit", "Changed my mind"], "which order are we working on?"
    )

    assert result is None


class _RaisingLLM:
    def with_structured_output(self, _model):
        return self

    def invoke(self, _messages):
        raise RuntimeError("simulated LLM failure")


def test_llm_failure_falls_back_to_none_not_a_crash(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(graph_module, "ChatOpenAI", lambda **_kwargs: _RaisingLLM())

    result = _attempt_free_text_slot_fill(["Wrong size/fit"], "too small")

    assert result is None


# --- end-to-end: free text during a mandatory RETURNS ask stage ---


def _drive_returns_to_reason_stage(order_number: str):
    config = _config()
    result = v2_agent_graph.invoke(
        {"userMessage": f"I want to return order {order_number}."}, config=config
    )
    interrupt_value = result["__interrupt__"][0].value

    # U-1002 has exactly one returnable item, so item-selection is skipped
    # and this lands straight on WAITING_FOR_REASON.
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "REASON_SELECTED"
    assert order_number in interrupt_value["message"]  # context-disclosure fix

    return config


def test_matching_free_text_reply_advances_past_the_reason_stage(monkeypatch):
    # Mocked at the _attempt_free_text_slot_fill boundary rather than by
    # setting a real OPENAI_API_KEY — classify_capability_node would
    # otherwise also see a (fake) key present and attempt a real network
    # call before falling back. These tests are about the gate's
    # integration with a slot-fill result, already covered in isolation
    # above; keeping OPENAI_API_KEY unset keeps the rest of the turn on
    # the same fast, offline deterministic path every other test uses.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Reach the REASON ask stage first, with slot-fill genuinely inert (no
    # API key) — only patch it to "match" for the free-text REPLY below,
    # otherwise it would also fire on the very first pass (before any
    # question was even asked) and skip straight past this stage's own
    # interrupt, which is a real and correct behavior but not what this
    # test is isolating.
    config = _drive_returns_to_reason_stage("U-1002")

    monkeypatch.setattr(
        graph_module, "_attempt_free_text_slot_fill", lambda candidates, message: "Wrong size/fit"
    )
    result = v2_agent_graph.invoke(
        Command(resume={"customerReply": "these run too small"}), config=config
    )

    # Advanced straight through to the next stage (method, or confirmation
    # if only one method) instead of re-asking "why are you returning this?"
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] in ("ASK_CUSTOMER", "CONFIRM_ACTION")
    if interrupt_value["interruptType"] == "ASK_CUSTOMER":
        assert interrupt_value["expectedInteractionType"] != "REASON_SELECTED"


def test_non_matching_free_text_falls_through_to_the_same_corrective_reask(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        graph_module, "_attempt_free_text_slot_fill", lambda candidates, message: None
    )
    config = _drive_returns_to_reason_stage("U-1002")

    result = v2_agent_graph.invoke(
        Command(resume={"customerReply": "which order are we working on?"}), config=config
    )

    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "REASON_SELECTED"
    assert "U-1002" in interrupt_value["message"]
