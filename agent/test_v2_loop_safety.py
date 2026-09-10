# agent/test_v2_loop_safety.py
#
# Loop safety (plan section 30): iteration cap, repeated-identical-call
# short-circuiting, per-tool retry-limit escalation, and the shared
# escalate() path always reaching a terminal status rather than hanging.
#
# The full-loop tests monkeypatch _deterministic_agent_reason so the agent
# can be forced into pathological behavior (always call the same tool,
# always call a failing tool) without needing a real, uncontrollable LLM —
# fast, free, deterministic.

import pytest

import v2.graph as graph_module
from v2 import loop_safety


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _config(suffix: str):
    return {"configurable": {"thread_id": f"loop-safety-{suffix}"}}


# --- full-loop, end-to-end behavior ---


def test_iteration_budget_exceeded_forces_graceful_escalation(monkeypatch):
    call_counter = {"n": 0}

    def always_call_a_valid_tool_with_varying_args(state, capability):
        call_counter["n"] += 1
        order_number = f"U-100{(call_counter['n'] % 5) + 1}"
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_order_status_tool",
            "toolArgs": {"order_number": order_number},
            "message": "",
            "uiProposal": [],
        }
        return state

    monkeypatch.setattr(
        graph_module, "_deterministic_agent_reason", always_call_a_valid_tool_with_varying_args
    )

    result = graph_module.v2_agent_graph.invoke(
        {"userMessage": "Where is order U-1001?"}, config=_config("iteration-cap")
    )

    assert result["status"] == "ERROR"
    assert result["loopIteration"] >= loop_safety.MAX_LOOP_ITERATIONS
    assert result["_escalationReason"] == "max_iterations"
    assert "specialist" in result["uiState"]["assistantMessage"].lower()


def test_repeated_identical_call_is_short_circuited_not_re_invoked(monkeypatch):
    def always_the_same_call(state, capability):
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_recent_orders_tool",
            "toolArgs": {},
            "message": "",
            "uiProposal": [],
        }
        return state

    monkeypatch.setattr(graph_module, "_deterministic_agent_reason", always_the_same_call)

    result = graph_module.v2_agent_graph.invoke(
        {"userMessage": "Where is my order?"}, config=_config("repeated-call")
    )

    tool_log = result["toolLog"]
    short_circuited = [
        entry for entry in tool_log if (entry.get("resultSummary") or {}).get("note")
    ]

    # At least one call was short-circuited (the "note" result, not a real
    # re-invocation) once the same (tool, args) pair repeated enough times.
    assert short_circuited
    # The agent never varies its decision, so this still eventually
    # escalates via the iteration cap — the short-circuit prevents wasted
    # tool calls, it doesn't by itself end the turn.
    assert result["status"] == "ERROR"
    assert result["_escalationReason"] == "max_iterations"


def test_retry_limit_escalates_faster_than_the_iteration_cap(monkeypatch):
    call_counter = {"n": 0}

    def always_a_failing_order_number(state, capability):
        call_counter["n"] += 1
        # A different (nonexistent) order number each time so this is
        # never treated as a repeated identical call — it's specifically
        # testing that the SAME TOOL failing repeatedly (regardless of
        # args) escalates on its own, faster than the iteration cap would.
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_order_status_tool",
            "toolArgs": {"order_number": f"U-999{call_counter['n']}"},
            "message": "",
            "uiProposal": [],
        }
        return state

    monkeypatch.setattr(graph_module, "_deterministic_agent_reason", always_a_failing_order_number)

    result = graph_module.v2_agent_graph.invoke(
        {"userMessage": "Where is order U-9990?"}, config=_config("retry-limit")
    )

    assert result["status"] == "ERROR"
    assert result["_escalationReason"].startswith("tool_retry_limit_exceeded")
    assert result["loopIteration"] < loop_safety.MAX_LOOP_ITERATIONS


def test_a_single_transient_failure_does_not_escalate():
    # Sanity check the retry-limit doesn't fire on a normal, one-off
    # not-found lookup — only on persistent repeated failure.
    result = graph_module.v2_agent_graph.invoke(
        {"userMessage": "Where is order U-9999?"}, config=_config("single-failure")
    )

    assert result["status"] == "FINAL"
    assert result.get("_escalationReason") is None


# --- pure-function unit coverage ---


def test_tool_call_signature_ignores_key_order():
    sig1 = loop_safety.tool_call_signature("get_order_status_tool", {"order_number": "U-1002", "x": 1})
    sig2 = loop_safety.tool_call_signature("get_order_status_tool", {"x": 1, "order_number": "U-1002"})

    assert sig1 == sig2


def test_is_repeated_call_true_after_two_prior_identical_calls():
    signature = loop_safety.tool_call_signature("get_recent_orders_tool", {})
    state = {"repeatedCallSignatures": [signature, signature], "_repeatedCallStage": "STAGE"}

    assert loop_safety.is_repeated_call(state, "get_recent_orders_tool", {}, "STAGE") is True


def test_is_repeated_call_false_with_only_one_prior_call():
    signature = loop_safety.tool_call_signature("get_recent_orders_tool", {})
    state = {"repeatedCallSignatures": [signature], "_repeatedCallStage": "STAGE"}

    assert loop_safety.is_repeated_call(state, "get_recent_orders_tool", {}, "STAGE") is False


def test_is_repeated_call_false_when_workflow_stage_has_moved_on():
    signature = loop_safety.tool_call_signature("get_recent_orders_tool", {})
    state = {"repeatedCallSignatures": [signature, signature], "_repeatedCallStage": "OLD_STAGE"}

    assert loop_safety.is_repeated_call(state, "get_recent_orders_tool", {}, "NEW_STAGE") is False


def test_record_call_signature_resets_list_when_workflow_stage_changes():
    signature = loop_safety.tool_call_signature("get_recent_orders_tool", {})
    state = {"repeatedCallSignatures": [signature, signature], "_repeatedCallStage": "OLD_STAGE"}

    loop_safety.record_call_signature(state, "get_recent_orders_tool", {}, "NEW_STAGE")

    assert state["_repeatedCallStage"] == "NEW_STAGE"
    assert len(state["repeatedCallSignatures"]) == 1


def test_consecutive_failure_count_stops_counting_at_a_success():
    state = {
        "toolLog": [
            {"toolName": "get_order_status_tool", "error": "boom"},
            {"toolName": "get_order_status_tool", "error": None},
            {"toolName": "get_order_status_tool", "error": "boom again"},
        ]
    }

    assert loop_safety.consecutive_failure_count(state, "get_order_status_tool") == 1


def test_consecutive_failure_count_ignores_a_different_tool_in_between():
    state = {
        "toolLog": [
            {"toolName": "get_order_status_tool", "error": "boom"},
            {"toolName": "get_order_status_tool", "error": "boom"},
            {"toolName": "get_recent_orders_tool", "error": None},
        ]
    }

    # Scanning backward from the most recent entry: the last entry is a
    # different tool entirely, so the count stops immediately at 0.
    assert loop_safety.consecutive_failure_count(state, "get_order_status_tool") == 0


def test_escalate_sets_a_graceful_message_and_terminal_status():
    state = {}

    result = loop_safety.escalate(state, "test_reason")

    assert result["status"] == "ERROR"
    assert result["_escalationReason"] == "test_reason"
    assert result["_decision"]["action"] == "FINISH"
    assert "specialist" in result["_decision"]["message"].lower()


def test_run_with_timeout_raises_on_a_slow_call():
    import time

    with pytest.raises(Exception):
        loop_safety.run_with_timeout(lambda: time.sleep(1), timeout_seconds=0.05)


def test_run_with_timeout_returns_the_result_of_a_fast_call():
    assert loop_safety.run_with_timeout(lambda: 42, timeout_seconds=5) == 42
