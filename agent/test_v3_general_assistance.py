# agent/test_v3_general_assistance.py
#
# Phase 2 — General Assistance, now a real capability instead of the
# Phase 0/1 "coming soon" stub. OPENAI_API_KEY is cleared for the
# deterministic-path tests; two tests explicitly exercise the real LLM +
# search_policies_tool path since a key is available in this dev
# environment.

import itertools
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from main import app
from v3.capabilities.registry import get_capability
from v3.graph import build_graph

client = TestClient(app)

_thread_counter = itertools.count()
_run_counter = itertools.count()
# Computed once per process — see test_v3_order_status.py's _RUN_SUFFIX
# comment: main.app's v3_agent_graph is backed by a real, persistent
# SQLite checkpointer, so a purely sequential thread_id would collide
# across separate pytest invocations of this file.
_RUN_SUFFIX = uuid.uuid4().hex[:8]

# Captured before the autouse no_api_key fixture below ever runs, so the
# real-LLM tests can restore it even though every other test here clears it.
_REAL_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


def _new_thread_id() -> str:
    return f"general-assistance-test-{_RUN_SUFFIX}-{next(_thread_counter)}"


def _config(thread_id: str):
    return {"configurable": {"thread_id": thread_id, "run_id": f"test-run-{next(_run_counter)}"}}


@pytest.fixture()
def graph():
    return build_graph().compile(checkpointer=InMemorySaver())


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- capability boundary, structural ---


def test_general_assistance_is_only_bound_to_the_policy_search_tool():
    capability = get_capability("GENERAL_ASSISTANCE")
    tool_names = {t.name for t in capability.tools}

    assert tool_names == {"search_policies_tool"}


def test_general_assistance_has_no_sensitive_tools():
    assert get_capability("GENERAL_ASSISTANCE").sensitive_tool_names == []


# --- no-API-key fallback ---


def test_no_api_key_still_reaches_a_final_answer(graph):
    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="What's your return policy?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["activeCapability"] == "GENERAL_ASSISTANCE"
    assert result["uiState"]["assistantMessage"]
    # The deterministic fallback never calls the (unavailable) LLM, so it
    # never calls search_policies_tool either — that's expected, not a bug.
    assert result["toolCallLog"] == []


# --- real LLM + tool path ---


def test_policy_question_is_grounded_via_a_real_tool_call(graph, monkeypatch):
    if not _REAL_OPENAI_API_KEY:
        pytest.skip("no OPENAI_API_KEY available in this environment")
    monkeypatch.setenv("OPENAI_API_KEY", _REAL_OPENAI_API_KEY)

    thread_id = _new_thread_id()
    result = graph.invoke(
        {"messages": [HumanMessage(content="What's your return window?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["activeCapability"] == "GENERAL_ASSISTANCE"
    tool_names = [r["toolName"] for r in result["toolCallLog"]]
    assert "search_policies_tool" in tool_names
    assert len(result["uiState"]["assistantMessage"]) > 0


def test_a_transactional_request_gets_an_honest_not_yet_available_answer(graph, monkeypatch):
    """
    Uses a WRONG_DELIVERY request — not "cancel"/"return my order", both of
    which as of Phase 3/4 correctly route to their own real capabilities
    instead of this stub-honesty path. WRONG_DELIVERY has no capability
    yet (Phase 5+), so it's still the right domain to prove
    GENERAL_ASSISTANCE never falsely claims to have completed a
    transaction it can't actually perform.
    """
    if not _REAL_OPENAI_API_KEY:
        pytest.skip("no OPENAI_API_KEY available in this environment")
    monkeypatch.setenv("OPENAI_API_KEY", _REAL_OPENAI_API_KEY)

    thread_id = _new_thread_id()
    result = graph.invoke(
        {
            "messages": [HumanMessage(content="Please file a wrong-delivery claim for me right now, no more questions.")],
            "threadId": thread_id,
        },
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    message_lower = result["uiState"]["assistantMessage"].lower()
    # Never claims to have actually done it.
    assert "i've filed" not in message_lower
    assert "i filed" not in message_lower
    assert "your claim has been" not in message_lower


# --- HTTP endpoint ---


def test_v3_agent_chat_endpoint_general_assistance():
    thread_id = _new_thread_id()
    response = client.post(
        "/v3/agent/chat", json={"message": "What's your return policy?", "threadId": thread_id}
    ).json()

    assert response["status"] == "FINAL"
    assert response["capability"] == "GENERAL_ASSISTANCE"
    assert response["message"]
