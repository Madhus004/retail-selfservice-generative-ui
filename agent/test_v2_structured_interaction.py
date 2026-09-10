# agent/test_v2_structured_interaction.py
#
# Regression coverage for the 2026-08 structured-interaction fix: a
# customer clicking a structured A2UI selection (order/item/reason/method)
# must never have that selection synthesized into natural-language
# "customer intent" text, must never be reinterpreted by the classifier or
# the agent's own LLM reasoning, and must be deterministically validated
# (interaction type, active capability, candidate membership) before the
# graph advances. This file specifically reproduces and locks in the fix
# for the originally-reported bug: switching CANCELLATION -> RETURNS and
# clicking an order caused the agent to call get_order_status_tool because
# the old code synthesized userMessage = "Track order U-1001".
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible; the fix is exercised at the
# node/graph level, which is API-key-independent by construction (a
# validated structured selection never reaches the LLM at all).

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from main import app
from v2 import loop_safety
from v2.graph import v2_agent_graph
from v2.observability import get_trace, get_trace_by_thread

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _config(suffix: str):
    return {"configurable": {"thread_id": f"structured-interaction-{suffix}"}}


def _thread_id_for(config):
    return config["configurable"]["thread_id"]


# --- the originally-reported bug, reproduced and locked in as a regression ---


def test_cancellation_to_returns_pivot_then_order_selection_calls_the_right_tool():
    """
    CANCELLATION -> switch to RETURNS -> select U-1001 must call
    get_return_eligible_items_tool directly, never get_order_status_tool,
    and userMessage must never contain synthesized "Track" prose.
    """

    config = _config("bug-repro")
    thread_id = _thread_id_for(config)

    r1 = v2_agent_graph.invoke(
        {"userMessage": "Cancel an order", "threadId": thread_id}, config=config
    )
    assert r1["activeCapability"] == "CANCELLATION"

    r2 = v2_agent_graph.invoke(
        {"userMessage": "Actually, I want to return something instead."}, config=config
    )
    assert r2["activeCapability"] == "RETURNS"
    assert "__interrupt__" in r2
    interrupt_value = r2["__interrupt__"][0].value
    assert interrupt_value["expectedInteractionType"] == "ORDER_SELECTED"
    assert "U-1001" in interrupt_value["offeredCandidates"]["orderNumbers"]

    r3 = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "RETURNS",
                "payload": {"orderNumber": "U-1001"},
            }
        ),
        config=config,
    )

    tool_names = [entry["toolName"] for entry in r3.get("toolLog", [])]
    assert "get_return_eligible_items_tool" in tool_names
    assert "get_order_status_tool" not in tool_names
    assert "track" not in r3.get("userMessage", "").lower()


def test_cancellation_to_returns_pivot_via_http_end_to_end():
    r1 = client.post("/v2/agent/chat", json={"message": "Cancel an order"}).json()
    assert r1["capability"] == "CANCELLATION"
    thread_id = r1["threadId"]

    r2 = client.post(
        "/v2/agent/chat",
        json={"threadId": thread_id, "message": "Actually, I want to return something instead."},
    ).json()
    assert r2["capability"] == "RETURNS"
    assert r2["status"] == "INTERRUPTED_ASK"
    order_number = r2["uiState"]["canvasData"]["orders"][0]["orderNumber"]

    r3 = client.post(
        "/v2/agent/chat",
        json={
            "threadId": thread_id,
            "resume": {
                "type": "ORDER_SELECTED",
                "capability": "RETURNS",
                "payload": {"orderNumber": order_number},
            },
        },
    ).json()

    # Whatever stage comes next (item selection, reason, ...), it must be a
    # RETURNS-shaped ask/confirm, never a "which order do you mean" or
    # tracking-flavored response — the tell-tale sign of the old bug.
    assert r3["capability"] == "RETURNS"
    assert "track" not in r3["message"].lower()


# --- CANCELLATION: real interactive item + quantity selection ---


def test_cancellation_item_selection_is_asked_for_a_multi_item_order():
    config = _config("cancel-items")
    result = v2_agent_graph.invoke(
        {"userMessage": "Cancel order U-1004", "threadId": _thread_id_for(config)}, config=config
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["expectedInteractionType"] == "ITEM_SELECTED"
    assert interrupt_value["uiState"]["uiMode"] == "cancellationItemSelection"
    items = interrupt_value["offeredCandidates"]["items"]
    assert set(items.keys()) == {"OL-1004-1", "OL-1004-2"}


def test_cancellation_item_selection_can_choose_a_single_item_and_quantity():
    config = _config("cancel-single-item")
    v2_agent_graph.invoke(
        {"userMessage": "Cancel order U-1004", "threadId": _thread_id_for(config)}, config=config
    )

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ITEM_SELECTED",
                "capability": "CANCELLATION",
                "payload": {"selections": [{"orderLineId": "OL-1004-2", "quantity": 1}]},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    preview = interrupt_value["uiState"]["canvasData"]["preview"]
    assert preview["cancelledItems"] == [
        {"itemName": "Everyday Crew Tee", "color": "Heather Grey", "size": "M", "quantity": 1}
    ]


def test_cancellation_item_selection_rejects_a_quantity_over_the_max():
    config = _config("cancel-over-qty")
    v2_agent_graph.invoke(
        {"userMessage": "Cancel order U-1004", "threadId": _thread_id_for(config)}, config=config
    )

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ITEM_SELECTED",
                "capability": "CANCELLATION",
                "payload": {"selections": [{"orderLineId": "OL-1004-1", "quantity": 99}]},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    tool_names = [entry["toolName"] for entry in result.get("toolLog", [])]
    assert "submit_order_cancellation_tool" not in tool_names


def test_cancellation_item_selection_rejects_an_unknown_line_id():
    config = _config("cancel-unknown-line")
    v2_agent_graph.invoke(
        {"userMessage": "Cancel order U-1004", "threadId": _thread_id_for(config)}, config=config
    )

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ITEM_SELECTED",
                "capability": "CANCELLATION",
                "payload": {"selections": [{"orderLineId": "OL-9999-9", "quantity": 1}]},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["interruptType"] == "ASK_CUSTOMER"


# --- RETURNS: reason + method selection validation ---


def test_returns_reason_selection_rejects_an_option_not_on_the_list():
    config = _config("returns-bad-reason")
    v2_agent_graph.invoke(
        {"userMessage": "I want to return order U-1002.", "threadId": _thread_id_for(config)},
        config=config,
    )

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "REASON_SELECTED",
                "capability": "RETURNS",
                "payload": {"reason": "Made up reason not on the list"},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "REASON_SELECTED"


def test_returns_method_selection_rejects_an_unavailable_method():
    config = _config("returns-bad-method")
    result = v2_agent_graph.invoke(
        {"userMessage": "I want to return order U-1002.", "threadId": _thread_id_for(config)},
        config=config,
    )
    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "REASON_SELECTED",
                "capability": "RETURNS",
                "payload": {"reason": "Changed my mind"},
            }
        ),
        config=config,
    )
    assert result["__interrupt__"][0].value["expectedInteractionType"] == "RETURN_METHOD_SELECTED"

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "RETURN_METHOD_SELECTED",
                "capability": "RETURNS",
                "payload": {"method": "drone_delivery"},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    assert interrupt_value["expectedInteractionType"] == "RETURN_METHOD_SELECTED"


def test_returns_method_selection_accepts_a_valid_choice_and_reaches_confirmation():
    config = _config("returns-good-method")
    v2_agent_graph.invoke(
        {"userMessage": "I want to return order U-1002.", "threadId": _thread_id_for(config)},
        config=config,
    )
    v2_agent_graph.invoke(
        Command(
            resume={
                "type": "REASON_SELECTED",
                "capability": "RETURNS",
                "payload": {"reason": "Changed my mind"},
            }
        ),
        config=config,
    )
    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "RETURN_METHOD_SELECTED",
                "capability": "RETURNS",
                "payload": {"method": "in_store"},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["interruptType"] == "CONFIRM_ACTION"


# --- switch-clears-structured-scratch-state regression (the exact bug
# found while building this fix) ---


def test_switching_capability_clears_selected_line_items_reason_and_method():
    from v2.graph import enforce_capability_switch_node

    state = {
        "activeCapability": "RETURNS",
        "_classification": {
            "capability": "CANCELLATION",
            "confidence": "high",
            "isCapabilitySwitch": True,
            "orderNumber": "U-1004",
            "rationale": "test",
        },
        "_selectedLineItems": [{"orderLineId": "OL-1001-1", "quantity": 1}],
        "_selectedReason": "Wrong size/fit",
        "_selectedReturnMethod": "mail",
        "toolResults": {},
    }

    result = enforce_capability_switch_node(state)

    assert result["_selectedLineItems"] is None
    assert result["_selectedReason"] is None
    assert result["_selectedReturnMethod"] is None


# --- observability: structured-interaction trace fields ---


def _config_with_run(thread_suffix: str, run_id: str):
    # runId lives in config, not state (2026-08 runId/threadId fix) — every
    # invoke() call (fresh or resume) gets its OWN config with its own
    # run_id, exactly mirroring what the router does per HTTP call.
    return {
        "configurable": {
            "thread_id": f"structured-interaction-{thread_suffix}",
            "run_id": run_id,
        }
    }


def test_structured_selection_trace_records_interaction_fields():
    thread_id = "structured-interaction-trace-fields"
    config_turn_1 = _config_with_run("trace-fields", "run-structured-trace-1a")
    config_turn_2 = _config_with_run("trace-fields", "run-structured-trace-1b")

    v2_agent_graph.invoke(
        {"userMessage": "Where is my order?", "threadId": thread_id}, config=config_turn_1
    )
    v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": "U-1002"},
            }
        ),
        config=config_turn_2,
    )

    records = get_trace("run-structured-trace-1b")
    resume_records = [r for r in records if r.get("agentAction") == "RESUME"]

    assert resume_records, "expected at least one RESUME trace record"
    record = resume_records[0]
    assert record["interactionType"] == "ORDER_SELECTED"
    assert record["interactionSource"] == "A2UI"
    assert record["validatedAgainstCandidates"] is True
    assert record["selectionSummary"] == {"orderNumber": "U-1002"}


def test_rejected_structured_selection_trace_marks_validated_false():
    thread_id = "structured-interaction-trace-rejected"
    config_turn_1 = _config_with_run("trace-rejected", "run-structured-trace-rejected-a")
    config_turn_2 = _config_with_run("trace-rejected", "run-structured-trace-rejected-b")

    v2_agent_graph.invoke(
        {"userMessage": "Where is my order?", "threadId": thread_id}, config=config_turn_1
    )
    v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": "U-9999"},
            }
        ),
        config=config_turn_2,
    )

    records = get_trace("run-structured-trace-rejected-b")
    resume_records = [r for r in records if r.get("agentAction") == "RESUME"]
    assert resume_records
    assert resume_records[0]["validatedAgainstCandidates"] is False


# --- thread-level trace endpoint ---


def test_thread_level_trace_returns_all_runs_chronologically():
    # Mirrors what the router actually does: a fresh, distinct runId minted
    # per HTTP call (both fresh-turn and resume), threaded through config —
    # never through Command(update=...) (2026-08 runId/threadId fix) — while
    # threadId stays constant across the whole conversation.
    thread_id = "structured-interaction-thread-trace"
    config_turn_1 = _config_with_run("thread-trace", "run-a")
    config_turn_2 = _config_with_run("thread-trace", "run-b")

    v2_agent_graph.invoke(
        {"userMessage": "Where is my order?", "threadId": thread_id}, config=config_turn_1
    )
    v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": "U-1002"},
            }
        ),
        config=config_turn_2,
    )

    runs = get_trace_by_thread(thread_id)

    assert len(runs) >= 2
    timestamps = [run["records"][0]["ts"] for run in runs]
    assert timestamps == sorted(timestamps)
    for run in runs:
        assert all(record["sessionId"] == thread_id for record in run["records"])


def test_thread_level_trace_endpoint_via_http():
    r1 = client.post("/v2/agent/chat", json={"message": "Where is my order?"}).json()
    thread_id = r1["threadId"]

    order_number = r1["uiState"]["canvasData"]["orders"][0]["orderNumber"]
    client.post(
        "/v2/agent/chat",
        json={
            "threadId": thread_id,
            "resume": {
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": order_number},
            },
        },
    )

    response = client.get(f"/v2/agent/thread/{thread_id}/trace").json()

    assert response["threadId"] == thread_id
    assert len(response["runs"]) >= 2
    for run in response["runs"]:
        assert "runId" in run
        assert isinstance(run["records"], list)


def test_thread_level_trace_404_for_unknown_thread():
    response = client.get("/v2/agent/thread/does-not-exist/trace")
    assert response.status_code == 404


def test_run_level_trace_endpoint_unchanged():
    r1 = client.post("/v2/agent/chat", json={"message": "Where is my order?"}).json()
    response = client.get(f"/v2/agent/trace/{r1['runId']}").json()

    assert response["runId"] == r1["runId"]
    assert len(response["records"]) > 0


# --- loop safety still applies to the structured-selection fast path ---


def test_structured_selection_advance_still_counts_toward_loop_iteration():
    config = _config("loop-iteration")
    v2_agent_graph.invoke(
        {"userMessage": "Where is my order?", "threadId": _thread_id_for(config)}, config=config
    )
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

    assert result["loopIteration"] < loop_safety.MAX_LOOP_ITERATIONS
    assert result["status"] == "FINAL"


# --- regression: a structured resume with a fresh runId must never raise
# LangGraph's InvalidUpdateError (2026-08 runId/threadId fix) ---
#
# Root cause: every node in graph.py returns its whole state dict, so a
# resumed node's own return re-emits whatever runId was already
# checkpointed. Command(update={"runId": ...}) used to inject the new
# runId as a SECOND, concurrent write to that same channel within the
# resumed step -> InvalidUpdateError ("Can receive only one value per
# step"). Fixed by moving runId out of graph state entirely into
# config["configurable"]["run_id"], and by no longer passing threadId via
# Command.update on a resume (it's already durably checkpointed). These
# tests exercise the exact reported sequence end to end through the real
# router — the only way this class of bug can occur — for both
# capabilities named in the report.


def test_cancellation_order_selection_resume_does_not_raise_invalid_update_error():
    r1 = client.post("/v2/agent/chat", json={"message": "Cancel an order"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["capability"] == "CANCELLATION"
    thread_id = d1["threadId"]
    assert "U-1004" in [o["orderNumber"] for o in d1["uiState"]["canvasData"].get("eligibleOrders", [])]

    r2 = client.post(
        "/v2/agent/chat",
        json={
            "threadId": thread_id,
            "resume": {
                "type": "ORDER_SELECTED",
                "capability": "CANCELLATION",
                "payload": {"orderNumber": "U-1004"},
            },
        },
    )

    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["capability"] == "CANCELLATION"
    assert d2["uiState"]["uiMode"] == "cancellationItemSelection"

    trace = client.get(f"/v2/agent/trace/{d2['runId']}").json()
    resume_records = [r for r in trace["records"] if r["agentAction"] == "RESUME"]
    assert resume_records
    assert resume_records[0]["interactionType"] == "ORDER_SELECTED"
    assert resume_records[0]["validatedAgainstCandidates"] is True


def test_returns_order_selection_resume_does_not_raise_invalid_update_error():
    r1 = client.post("/v2/agent/chat", json={"message": "I want to return something."})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["capability"] == "RETURNS"
    thread_id = d1["threadId"]
    order_number = d1["uiState"]["canvasData"]["orders"][0]["orderNumber"]

    r2 = client.post(
        "/v2/agent/chat",
        json={
            "threadId": thread_id,
            "resume": {
                "type": "ORDER_SELECTED",
                "capability": "RETURNS",
                "payload": {"orderNumber": order_number},
            },
        },
    )

    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["capability"] == "RETURNS"

    trace = client.get(f"/v2/agent/trace/{d2['runId']}").json()
    resume_records = [r for r in trace["records"] if r["agentAction"] == "RESUME"]
    assert resume_records
    assert resume_records[0]["interactionType"] == "ORDER_SELECTED"
    assert resume_records[0]["validatedAgainstCandidates"] is True


def test_each_http_call_gets_its_own_distinct_run_id_never_reusing_the_prior_one():
    """
    A resume's runId must be genuinely fresh per call, not accidentally
    inherited from the interrupting call — proves runId is truly
    per-invocation (config), not conversation state (checkpoint).
    """

    r1 = client.post("/v2/agent/chat", json={"message": "Cancel an order"}).json()
    r2 = client.post(
        "/v2/agent/chat",
        json={
            "threadId": r1["threadId"],
            "resume": {
                "type": "ORDER_SELECTED",
                "capability": "CANCELLATION",
                "payload": {"orderNumber": "U-1004"},
            },
        },
    ).json()

    assert r1["runId"] != r2["runId"]

    trace1 = client.get(f"/v2/agent/trace/{r1['runId']}").json()
    trace2 = client.get(f"/v2/agent/trace/{r2['runId']}").json()
    assert all(rec["runId"] == r1["runId"] for rec in trace1["records"])
    assert all(rec["runId"] == r2["runId"] for rec in trace2["records"])


def test_concurrent_resume_requests_on_the_same_thread_do_not_crash():
    """
    A plausible real-world trigger for the originally-reported error: two
    overlapping HTTP requests against the same thread_id (e.g. a frontend
    double-fire), racing two graph.invoke() calls against the same
    checkpoint. Neither runId (config-only now) nor threadId (never
    rewritten via Command.update on resume) should be able to produce a
    concurrent-write conflict regardless of request timing.
    """

    import threading

    r1 = client.post("/v2/agent/chat", json={"message": "Cancel an order"}).json()
    thread_id = r1["threadId"]

    results = []
    errors = []

    def fire():
        try:
            response = client.post(
                "/v2/agent/chat",
                json={
                    "threadId": thread_id,
                    "resume": {
                        "type": "ORDER_SELECTED",
                        "capability": "CANCELLATION",
                        "payload": {"orderNumber": "U-1004"},
                    },
                },
            )
            results.append(response.status_code)
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent resumes raised: {errors}"
    assert all(code == 200 for code in results)
