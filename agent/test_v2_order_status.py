# agent/test_v2_order_status.py
#
# Full agent/tool loop tests for V2's ORDER_STATUS capability. OPENAI_API_KEY
# is cleared so these run the deterministic fallback path — fast, free, and
# reproducible, exercising the same loop shape a real LLM would drive
# (classify -> enforce_capability_switch -> agent_reason -> execute_tool ->
# agent_reason -> finish/ask_customer) without depending on model behavior.
#
# A checkpointer is required as of Phase 2 (test_v2_interrupt_pivot.py
# covers the resume/pivot mechanics in depth) — every direct graph.invoke()
# call here needs its own thread_id.

import itertools

import pytest
from fastapi.testclient import TestClient

from main import app
from v2.graph import v2_agent_graph

client = TestClient(app)

_thread_counter = itertools.count()


def _config():
    return {"configurable": {"thread_id": f"order-status-test-{next(_thread_counter)}"}}


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_known_order_number_calls_status_tool_directly_and_finishes():
    result = v2_agent_graph.invoke({"userMessage": "Where is order U-1002?"}, config=_config())

    assert result["status"] == "FINAL"
    assert result["uiState"]["uiMode"] == "orderStatus"
    assert [entry["toolName"] for entry in result["toolLog"]] == ["get_order_status_tool"]
    assert result["loopIteration"] == 1


def test_unknown_order_number_asks_which_order_after_listing_recent_ones():
    # Since Phase 2, ORDER_STATUS's own ask_customer is a real interrupt —
    # the turn pauses rather than finishing with a "which order?" message.
    result = v2_agent_graph.invoke({"userMessage": "Where is my order?"}, config=_config())

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["uiState"]["uiMode"] == "orderSelection"
    assert interrupt_value["uiState"]["canvasData"]["orders"]
    assert [entry["toolName"] for entry in result["toolLog"]] == ["get_recent_orders_tool"]


def test_a_nonexistent_order_number_surfaces_as_a_tool_error_not_a_crash():
    result = v2_agent_graph.invoke({"userMessage": "Where is order U-9999?"}, config=_config())

    assert result["status"] == "FINAL"
    assert result["toolLog"][0]["toolName"] == "get_order_status_tool"
    assert result["toolLog"][0]["error"] is not None


def test_a2ui_components_are_present_and_validated():
    result = v2_agent_graph.invoke({"userMessage": "Where is order U-1002?"}, config=_config())

    assert result["a2uiComponents"][0]["type"] in {"orderStatus", "orderSelection", "welcome"}
    assert result["a2uiOrigin"] in {"AGENT_PROPOSED", "DETERMINISTIC_FALLBACK"}


def test_out_of_scope_tool_name_is_rejected_not_executed():
    # Defense-in-depth check (plan section 30): execute_tool must refuse a
    # tool name that isn't in the active capability's tool list, even if
    # something upstream ever proposed one.
    from v2.graph import execute_tool_node

    state = {
        "activeCapability": "ORDER_STATUS",
        "_decision": {"action": "CALL_TOOL", "toolName": "submit_order_cancellation", "toolArgs": {}},
        "toolLog": [],
        "toolResults": {},
        "loopIteration": 0,
    }

    result = execute_tool_node(state)

    assert result["toolResults"]["submit_order_cancellation"]["error"]
    assert result["toolLog"][0]["error"] is not None


def test_v2_agent_chat_endpoint_returns_expected_shape():
    response = client.post("/v2/agent/chat", json={"message": "Where is order U-1002?"})

    assert response.status_code == 200
    body = response.json()
    assert body["capability"] == "ORDER_STATUS"
    assert body["orderNumber"] == "U-1002"
    assert body["status"] == "FINAL"
    assert body["uiState"]["uiMode"] == "orderStatus"


def test_v2_health_endpoint():
    response = client.get("/v2/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "engine": "v2"}
