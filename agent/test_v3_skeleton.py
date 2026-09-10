# agent/test_v3_skeleton.py
#
# Phase 0 — proves the V3 skeleton (state schema, messages-list assembly,
# SQLite persistence) works correctly before Phase 1 builds a real
# capability on top of it.
#
# Most tests here use build_graph() with a fresh InMemorySaver per test —
# same fast/isolated philosophy V2's whole test suite uses — rather than
# the actual SQLite-backed v3_agent_graph singleton the running app uses
# (that would mean every test run permanently writes into the local dev
# database). SQLite durability itself gets its own dedicated test below,
# against a throwaway temp file, so it's still proven for real rather than
# assumed.
#
# OPENAI_API_KEY is cleared for the deterministic-path tests so they're
# fast, free, and reproducible; one test explicitly exercises the real-LLM
# path since a key is available in this dev environment.

import itertools
import os
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from v3.graph import build_graph

# Captured before the autouse no_api_key fixture below ever runs, so the
# one real-LLM test can restore it even though every other test in this
# file deliberately clears it.
_REAL_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

_thread_counter = itertools.count()
_run_counter = itertools.count()


def _new_thread_id() -> str:
    return f"v3-skeleton-test-{next(_thread_counter)}"


def _config(thread_id: str):
    """
    A fresh run_id every call, same thread_id across a conversation —
    exactly how router.py invokes the graph (a brand-new uuid4 per HTTP
    call, never reused). Reusing one run_id across multiple invoke() calls
    on the same thread turns out to confuse LangGraph's checkpoint
    continuation (confirmed by direct repro) — this helper exists
    specifically so no test accidentally does that.
    """

    return {"configurable": {"thread_id": thread_id, "run_id": f"test-run-{next(_run_counter)}"}}


@pytest.fixture()
def isolated_graph():
    return build_graph().compile(checkpointer=InMemorySaver())


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- basic shape ---


def test_graph_imports_and_compiles():
    from v3.graph import v3_agent_graph  # the real, SQLite-backed singleton

    assert v3_agent_graph is not None


def test_fresh_turn_reaches_final_with_the_deterministic_fallback(isolated_graph):
    # Deliberately NOT an order-status phrase — ORDER_STATUS is now a real
    # capability (Phase 1) with its own dedicated test file
    # (test_v3_order_status.py); this file's job is just the GENERAL_
    # ASSISTANCE stub/skeleton mechanics.
    thread_id = _new_thread_id()
    result = isolated_graph.invoke(
        {"messages": [HumanMessage(content="What's your return policy?")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert result["activeCapability"] == "GENERAL_ASSISTANCE"
    assert result["uiState"]["assistantMessage"]
    assert isinstance(result["messages"][-1], AIMessage)


def test_messages_accumulate_across_turns_on_the_same_thread(isolated_graph):
    thread_id = _new_thread_id()
    first = isolated_graph.invoke(
        {"messages": [HumanMessage(content="Hello")], "threadId": thread_id}, config=_config(thread_id)
    )
    assert len(first["messages"]) == 2  # 1 human + 1 ai

    second = isolated_graph.invoke(
        {"messages": [HumanMessage(content="Second message")], "threadId": thread_id},
        config=_config(thread_id),
    )
    assert len(second["messages"]) == 4  # both turns preserved, nothing overwritten
    assert second["messages"][0].content == "Hello"
    assert second["messages"][2].content == "Second message"


def test_agent_reason_returns_only_the_delta_never_the_full_history(isolated_graph):
    """
    The exact discipline that makes the add_messages reducer safe to rely
    on — a node returning the FULL accumulated list back as its own
    "delta" would double it up on every turn. Verified here directly
    rather than just trusted, since this is precisely the class of subtle
    state-shape bug the whole V3 rebuild exists to close off for good.
    """

    thread_id = _new_thread_id()
    isolated_graph.invoke(
        {"messages": [HumanMessage(content="One")], "threadId": thread_id}, config=_config(thread_id)
    )
    result = isolated_graph.invoke(
        {"messages": [HumanMessage(content="Two")], "threadId": thread_id}, config=_config(thread_id)
    )

    assert len(result["messages"]) == 4  # not 6, 8, ... — no doubling


def test_trace_records_are_emitted_for_each_step(isolated_graph):
    from v3.observability import get_trace

    thread_id = _new_thread_id()
    config = _config(thread_id)
    run_id = config["configurable"]["run_id"]
    isolated_graph.invoke({"messages": [HumanMessage(content="Hi")], "threadId": thread_id}, config=config)

    records = get_trace(run_id)
    actions = [r["agentAction"] for r in records]
    assert "CLASSIFY" in actions
    assert "FINISH" in actions


# --- real LLM path (this dev environment has a key available) ---


def test_real_llm_path_produces_a_genuine_response(isolated_graph, monkeypatch):
    if not _REAL_OPENAI_API_KEY:
        pytest.skip("no OPENAI_API_KEY available in this environment")

    monkeypatch.setenv("OPENAI_API_KEY", _REAL_OPENAI_API_KEY)  # undo the autouse fixture, just for this test

    thread_id = _new_thread_id()
    result = isolated_graph.invoke(
        {"messages": [HumanMessage(content="Say hi back in exactly three words.")], "threadId": thread_id},
        config=_config(thread_id),
    )

    assert result["status"] == "FINAL"
    assert len(result["uiState"]["assistantMessage"]) > 0


# --- SQLite persistence, for real, against a throwaway file ---


def test_sqlite_checkpoint_survives_a_reconnect():
    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        thread_id = "sqlite-persistence-test"

        conn1 = sqlite3.connect(db_path, check_same_thread=False)
        graph1 = build_graph().compile(checkpointer=SqliteSaver(conn1))
        graph1.invoke(
            {"messages": [HumanMessage(content="Remember the number 42.")], "threadId": thread_id},
            config={"configurable": {"thread_id": thread_id, "run_id": "run-1"}},
        )
        conn1.close()

        # A brand-new connection/graph instance, simulating a process
        # restart — proves the checkpoint lives in the FILE, not just this
        # process's memory.
        conn2 = sqlite3.connect(db_path, check_same_thread=False)
        graph2 = build_graph().compile(checkpointer=SqliteSaver(conn2))
        state = graph2.get_state({"configurable": {"thread_id": thread_id}})
        conn2.close()

        assert state.values["messages"][0].content == "Remember the number 42."
