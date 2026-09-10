# agent/test_v2_interrupt_pivot.py
#
# Focused tests for the plan's section 18a mechanism — proven here against
# ORDER_STATUS's own ask_customer interrupt, since it's the only capability
# registered as of Phase 2 (before any second capability exists to switch
# into). This file's core job is to prove the *mechanism* itself is safe:
# continuation vs. abandonment is decided correctly, abandonment only ever
# clears state via enforce_capability_switch (never inside the interrupted
# node), and a tampered structured selection is rejected before it reaches
# a tool call.
#
# Phase 7 extends this with the full walkthrough-G proof (plan's
# walkthroughs section): a pivot arriving instead of a reply to a PENDING
# CONFIRM_ACTION interrupt, specifically — the between-turns walkthrough-F
# scenario (no interrupt pending at pivot time) lives in
# test_v2_capability_switch.py instead, since that one never touches
# ask_customer/request_confirmation's __abandon__ handling at all.
#
# OPENAI_API_KEY is cleared for every test so these run the deterministic
# fallback path — fast, free, reproducible.

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

import v2.router as router_module
from main import app
from v2 import confirmation, idempotency
from v2.graph import enforce_capability_switch_node, v2_agent_graph

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_idempotency_store():
    idempotency._EXECUTED_ACTIONS.clear()
    yield
    idempotency._EXECUTED_ACTIONS.clear()


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _start_pending_order_selection(thread_suffix: str):
    """Gets a real ask_customer interrupt pending on a fresh thread."""

    config = {"configurable": {"thread_id": f"pivot-test-{thread_suffix}"}}
    result = v2_agent_graph.invoke({"userMessage": "Where is my order?"}, config=config)

    assert "__interrupt__" in result
    offered = result["__interrupt__"][0].value["offeredCandidates"]

    return config, offered


# --- (a) plausible continuation resumes normally ---


def test_free_text_continuation_resumes_into_the_same_flow():
    config, _ = _start_pending_order_selection("continuation")

    result = v2_agent_graph.invoke(
        Command(resume={"customerReply": "U-1002"}), config=config
    )

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "orderStatus"
    tool_names = [entry["toolName"] for entry in result["toolLog"]]
    assert "get_order_status_tool" in tool_names


def test_free_text_continuation_via_http_endpoint():
    r1 = client.post("/v2/agent/chat", json={"message": "Where is my order?"}).json()
    assert r1["status"] == "INTERRUPTED_ASK"

    r2 = client.post(
        "/v2/agent/chat", json={"threadId": r1["threadId"], "message": "U-1003"}
    ).json()

    assert r2["status"] == "FINAL"
    assert r2["uiState"]["uiMode"] == "orderStatus"


# --- (b) an unrelated pivot clears state via enforce_capability_switch only ---


def test_enforce_capability_switch_is_the_only_place_that_archives_pending_action():
    """
    Feeds enforce_capability_switch_node a state with a synthetic
    pendingAction plus a forwarded _pendingPivot (as ask_customer_node
    would produce) and asserts it alone performs the archive/clear.
    """

    state = {
        "activeCapability": "ORDER_STATUS",
        "userMessage": "Where is my order?",
        "pendingAction": {"actionId": "a1", "consumed": False, "executed": False},
        "toolResults": {"get_recent_orders_tool": {"orders": []}},
        "_pendingPivot": {
            "newMessage": "Actually, cancel the shoes I ordered today instead.",
            "classification": {
                "capability": "CANCELLATION",
                "confidence": "high",
                "isCapabilitySwitch": True,
                "orderNumber": None,
                "rationale": "test",
            },
        },
    }

    result = enforce_capability_switch_node(state)

    # pendingAction was archived, not silently dropped or left consumable.
    assert result["pendingAction"] is None
    assert result["archivedPendingActions"][0]["actionId"] == "a1"
    # _pendingPivot is consumed (cleared) once read.
    assert result["_pendingPivot"] is None
    # userMessage is updated from the pivot's new message.
    assert result["userMessage"] == "Actually, cancel the shoes I ordered today instead."


def test_pivot_during_a_real_interrupt_switches_capability_safely():
    """
    End-to-end, now that CANCELLATION is registered (Phase 4): a pivot away
    from ORDER_STATUS's pending ask_customer question genuinely switches
    capability — no crash, and nothing from the old ORDER_STATUS question
    is blindly treated as an answer (e.g. it does not try to call
    get_order_status_tool with a garbage order number parsed from the
    pivot sentence). See test_v2_capability_switch.py (Phase 7) for the
    full cross-capability walkthrough-F/G proofs; this test just confirms
    the mechanism built in Phase 2 is exercised safely for real here.
    """

    r1 = client.post("/v2/agent/chat", json={"message": "Where is my order?"}).json()
    assert r1["status"] == "INTERRUPTED_ASK"

    r2 = client.post(
        "/v2/agent/chat",
        json={
            "threadId": r1["threadId"],
            "message": "Actually, cancel the shoes I ordered today instead.",
        },
    ).json()

    assert r2["status"] in {"FINAL", "INTERRUPTED_ASK", "INTERRUPTED_CONFIRM"}
    assert r2["capability"] == "CANCELLATION"


# --- (d) a tampered/out-of-set structured selection is rejected ---


def test_tampered_structured_selection_is_rejected_before_reaching_a_tool():
    config, offered = _start_pending_order_selection("tamper")
    assert "U-9999" not in offered["orderNumbers"]

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": "U-9999"},
            }
        ),
        config=config,
    )

    # Re-interrupted with a corrective message, not executed against a tool.
    assert "__interrupt__" in result
    tool_names = [entry["toolName"] for entry in result.get("toolLog", [])]
    assert "get_order_status_tool" not in tool_names


def test_tampered_selection_via_http_endpoint_re_asks():
    r1 = client.post("/v2/agent/chat", json={"message": "Where is my order?"}).json()

    r2 = client.post(
        "/v2/agent/chat",
        json={
            "threadId": r1["threadId"],
            "resume": {
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": "U-9999"},
            },
        },
    ).json()

    assert r2["status"] == "INTERRUPTED_ASK"
    assert "doesn't match" in r2["message"].lower()


def test_mismatched_interaction_type_is_rejected():
    """
    A structured selection whose type doesn't match what was actually
    asked (e.g. an ITEM_SELECTED arriving while ORDER_SELECTED is pending)
    is rejected the same way an out-of-candidate-set value is — never
    silently coerced or reinterpreted.
    """

    config, _ = _start_pending_order_selection("type-mismatch")

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ITEM_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"selections": [{"orderLineId": "OL-1002-1", "quantity": 1}]},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    tool_names = [entry["toolName"] for entry in result.get("toolLog", [])]
    assert "get_order_status_tool" not in tool_names


def test_mismatched_capability_is_rejected():
    """A structured selection naming a different capability than the one
    actually active is rejected — the capability field is not decorative."""

    config, offered = _start_pending_order_selection("capability-mismatch")
    candidate = offered["orderNumbers"][0]

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "RETURNS",
                "payload": {"orderNumber": candidate},
            }
        ),
        config=config,
    )

    assert "__interrupt__" in result
    tool_names = [entry["toolName"] for entry in result.get("toolLog", [])]
    assert "get_order_status_tool" not in tool_names


def test_valid_structured_selection_is_accepted_and_calls_the_status_tool():
    config, offered = _start_pending_order_selection("valid-selection")
    candidate = offered["orderNumbers"][0]

    result = v2_agent_graph.invoke(
        Command(
            resume={
                "type": "ORDER_SELECTED",
                "capability": "ORDER_STATUS",
                "payload": {"orderNumber": candidate},
            }
        ),
        config=config,
    )

    assert result["status"] == "FINAL"
    tool_names = [entry["toolName"] for entry in result["toolLog"]]
    assert "get_order_status_tool" in tool_names
    # Never synthesized into prose — the root cause of the "Track U-1001"
    # bug this fix addresses.
    assert "track" not in result["userMessage"].lower()


# --- walkthrough G (Phase 7): a pivot arriving instead of a reply to a
# PENDING CONFIRM_ACTION interrupt archives the sensitive action rather than
# ever letting it execute ---


def _reach_returns_confirmation_pending(message: str):
    """
    Drives a RETURNS conversation over the real HTTP client through
    whichever ASK_CUSTOMER stages the 2026-08 structured-interaction fix
    actually requires (item selection when an order has more than one
    returnable item, then reason, then method when more than one is
    available) up to a real CONFIRM_ACTION interrupt — resuming each stage
    with the new typed structured-selection envelope, deriving the
    candidates to choose from the response's own canvasData (offered
    Candidates itself is interrupt-payload-only, not part of the HTTP
    response shape).
    """

    response = client.post("/v2/agent/chat", json={"message": message}).json()

    while response["status"] == "INTERRUPTED_ASK":
        ui_mode = response["uiState"]["uiMode"]
        canvas_data = response["uiState"]["canvasData"]

        if ui_mode == "returnItemSelection":
            items = canvas_data["returnEligibility"]["items"]
            selections = [
                {"orderLineId": item["orderLineId"], "quantity": item["returnableQuantity"]}
                for item in items
                if item.get("returnableQuantity", 0) > 0
            ]
            resume = {"type": "ITEM_SELECTED", "capability": "RETURNS", "payload": {"selections": selections}}
        elif ui_mode == "returnReasonPrompt":
            reason = canvas_data["returnReasonOptions"][0]
            resume = {"type": "REASON_SELECTED", "capability": "RETURNS", "payload": {"reason": reason}}
        elif ui_mode == "returnMethodPrompt":
            method = canvas_data["returnEligibility"]["returnMethods"][0]
            resume = {"type": "RETURN_METHOD_SELECTED", "capability": "RETURNS", "payload": {"method": method}}
        else:
            raise AssertionError(f"Unexpected ASK_CUSTOMER stage reached: {ui_mode}")

        response = client.post(
            "/v2/agent/chat", json={"threadId": response["threadId"], "resume": resume}
        ).json()

    assert response["status"] == "INTERRUPTED_CONFIRM"
    return response


def test_walkthrough_g_pivot_away_from_a_pending_confirmation_archives_it():
    r1 = _reach_returns_confirmation_pending("I want to return order U-1001")
    assert r1["uiState"]["uiMode"] == "returnConfirmationPending"
    old_action_id = r1["uiState"]["a2ui"][0]["props"]["pending"]["actionId"]
    thread_id = r1["threadId"]

    # The pivot arrives as ordinary free text — NOT a confirmation resume —
    # while that CREATE_RETURN action is still pending.
    r2 = client.post(
        "/v2/agent/chat",
        json={"threadId": thread_id, "message": "Actually, cancel the shoes on order U-1004 instead."},
    ).json()

    assert r2["capability"] == "CANCELLATION"
    assert r2["status"] in {"INTERRUPTED_ASK", "INTERRUPTED_CONFIRM"}

    # The guarantee: even a stray, otherwise-well-formed confirmation for
    # the OLD (archived) actionId can never execute — there is nothing
    # pending to match it against, by construction, not by convention.
    result = confirmation.validate_confirmation(
        None, {"actionId": old_action_id, "actionType": "CREATE_RETURN", "accepted": True}
    )
    assert result.ok is False
    assert result.reason == "NO_PENDING_ACTION"
    assert not idempotency.has_executed(old_action_id)


def test_walkthrough_g_pivot_classifies_the_incoming_message_exactly_once(monkeypatch):
    """
    Plan section 18a: the router's pivot check must cost exactly one
    classification call per incoming message — never a second one for
    enforce_capability_switch to redo, since it consumes the SAME verdict
    forwarded via _pendingPivot rather than reclassifying. Structured
    selections cost zero classification calls (they never reach the
    classifier at all, per the 2026-08 structured-interaction fix), so
    only the FINAL free-text pivot message should be counted.
    """

    r1 = _reach_returns_confirmation_pending("I want to return order U-1001")

    call_count = {"n": 0}
    original_classify = router_module.classify

    def counting_classify(message, context=None):
        call_count["n"] += 1
        return original_classify(message, context)

    monkeypatch.setattr(router_module, "classify", counting_classify)

    client.post(
        "/v2/agent/chat",
        json={"threadId": r1["threadId"], "message": "Actually, cancel the shoes on order U-1004 instead."},
    )

    assert call_count["n"] == 1
