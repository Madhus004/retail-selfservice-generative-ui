# agent/test_v2_premature_execution.py
#
# Explicit proof, per the 2026-08 premature-execution-fix authorization,
# that each sensitive action's underlying mutation-shaped function —
# tools.submit_order_cancellation (via v2/tools/cancellation_tools.py's
# module-level import), v2/tools/returns_tools.py's create_return, and
# v2/tools/wrong_delivery_tools.py's submit_wrong_delivery_claim — is
# invoked ZERO times before a valid structured Confirm and EXACTLY ONCE
# after one, including a double-click/replay scenario where the same
# already-confirmed action is resumed a second time.
#
# Before this fix, request_confirmation_node ran the real sensitive tool
# itself as a "dry-run preview" — since LangGraph's interrupt() semantics
# re-execute everything before the interrupt() call on every resume, this
# meant the real, ID-minting, "status": "submitted" function actually ran
# once per resume (typed-yes reminders, re-interrupts, the final confirm),
# producing a different transaction id each time for one logical action.
# request_confirmation_node now calls a preview/validate-only function
# instead (validate_cancellation_proposal / build_return_preview /
# build_wrong_delivery_claim_preview) that never touches the real,
# mutation-shaped function at all — these tests prove that with a spy,
# not just by inspecting output shape.

import pytest
from unittest.mock import MagicMock
from langgraph.types import Command

from v2 import idempotency
from v2.graph import v2_agent_graph
import v2.tools.cancellation_tools as cancellation_tools
import v2.tools.returns_tools as returns_tools
import v2.tools.wrong_delivery_tools as wrong_delivery_tools


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def clear_idempotency_store():
    idempotency._EXECUTED_ACTIONS.clear()
    yield
    idempotency._EXECUTED_ACTIONS.clear()


def _config(suffix: str):
    return {"configurable": {"thread_id": f"premature-exec-test-{suffix}"}}


def _drive_cancellation_to_confirmation(order_number: str, thread_suffix: str):
    config = _config(thread_suffix)
    result = v2_agent_graph.invoke(
        {"userMessage": f"Cancel order {order_number}", "threadId": config["configurable"]["thread_id"]},
        config=config,
    )
    interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ORDER_SELECTED":
        result = v2_agent_graph.invoke(
            Command(resume={"type": "ORDER_SELECTED", "capability": "CANCELLATION", "payload": {"orderNumber": order_number}}),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    if interrupt_value["interruptType"] == "ASK_CUSTOMER" and interrupt_value["expectedInteractionType"] == "ITEM_SELECTED":
        item_candidates = interrupt_value["offeredCandidates"]["items"]
        selections = [
            {"orderLineId": line_id, "quantity": info["maxQuantity"]}
            for line_id, info in item_candidates.items()
        ]
        result = v2_agent_graph.invoke(
            Command(resume={"type": "ITEM_SELECTED", "capability": "CANCELLATION", "payload": {"selections": selections}}),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    return config, interrupt_value["actionId"], interrupt_value["actionType"]


def _drive_return_to_confirmation(order_number: str, thread_suffix: str):
    config = _config(thread_suffix)
    result = v2_agent_graph.invoke(
        {"userMessage": f"I want to return order {order_number}.", "threadId": config["configurable"]["thread_id"]},
        config=config,
    )
    interrupt_value = result["__interrupt__"][0].value

    while interrupt_value["interruptType"] == "ASK_CUSTOMER":
        interaction_type = interrupt_value["expectedInteractionType"]
        candidates = interrupt_value["offeredCandidates"]

        if interaction_type == "ITEM_SELECTED":
            selections = [
                {"orderLineId": line_id, "quantity": info["maxQuantity"]}
                for line_id, info in candidates["items"].items()
            ]
            payload = {"selections": selections}
        elif interaction_type == "REASON_SELECTED":
            payload = {"reason": candidates["reasons"][0]}
        elif interaction_type == "RETURN_METHOD_SELECTED":
            payload = {"method": candidates["methods"][0]}
        else:
            raise AssertionError(f"Unexpected ASK_CUSTOMER stage: {interaction_type}")

        result = v2_agent_graph.invoke(
            Command(resume={"type": interaction_type, "capability": "RETURNS", "payload": payload}),
            config=config,
        )
        interrupt_value = result["__interrupt__"][0].value

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    return config, interrupt_value["actionId"], interrupt_value["actionType"]


def _drive_wrong_delivery_to_confirmation(order_number: str, thread_suffix: str):
    config = _config(thread_suffix)
    result = v2_agent_graph.invoke(
        {
            "userMessage": f"It says delivered but I never received order {order_number}.",
            "threadId": config["configurable"]["thread_id"],
        },
        config=config,
    )
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    return config, interrupt_value["actionId"], interrupt_value["actionType"]


# --- CANCELLATION ---


def test_submit_order_cancellation_zero_before_one_after_confirm(monkeypatch):
    spy = MagicMock(wraps=cancellation_tools.submit_order_cancellation)
    monkeypatch.setattr(cancellation_tools, "submit_order_cancellation", spy)

    config, action_id, action_type = _drive_cancellation_to_confirmation("U-1004", "cancel-spy")

    # Nothing before Confirm — not the order/item ASK_CUSTOMER stages, not
    # the PENDING preview screen itself — ever called the real function.
    assert spy.call_count == 0

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 1


def test_submit_order_cancellation_not_called_again_on_double_click_replay(monkeypatch):
    spy = MagicMock(wraps=cancellation_tools.submit_order_cancellation)
    monkeypatch.setattr(cancellation_tools, "submit_order_cancellation", spy)

    config, action_id, action_type = _drive_cancellation_to_confirmation("U-1004", "cancel-double-click")

    confirm = Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}})
    first = v2_agent_graph.invoke(confirm, config=config)
    assert spy.call_count == 1
    first_result = first["toolResults"]["submit_order_cancellation_tool"]

    # Simulate a double-click: the exact same resume payload arrives again
    # on the same thread after the action has already completed.
    second = v2_agent_graph.invoke(confirm, config=config)

    assert spy.call_count == 1  # still exactly one real execution
    assert second["toolResults"]["submit_order_cancellation_tool"] == first_result


# --- RETURNS ---


def test_create_return_zero_before_one_after_confirm(monkeypatch):
    spy = MagicMock(wraps=returns_tools.create_return)
    monkeypatch.setattr(returns_tools, "create_return", spy)

    config, action_id, action_type = _drive_return_to_confirmation("U-1002", "return-spy")

    assert spy.call_count == 0

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 1


def test_create_return_not_called_again_on_double_click_replay(monkeypatch):
    spy = MagicMock(wraps=returns_tools.create_return)
    monkeypatch.setattr(returns_tools, "create_return", spy)

    config, action_id, action_type = _drive_return_to_confirmation("U-1002", "return-double-click")

    confirm = Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}})
    v2_agent_graph.invoke(confirm, config=config)
    assert spy.call_count == 1

    v2_agent_graph.invoke(confirm, config=config)
    assert spy.call_count == 1


# --- WRONG_DELIVERY ---


def test_submit_wrong_delivery_claim_zero_before_one_after_confirm(monkeypatch):
    spy = MagicMock(wraps=wrong_delivery_tools.submit_wrong_delivery_claim)
    monkeypatch.setattr(wrong_delivery_tools, "submit_wrong_delivery_claim", spy)

    config, action_id, action_type = _drive_wrong_delivery_to_confirmation("U-1002", "claim-spy")

    assert spy.call_count == 0

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 1


def test_submit_wrong_delivery_claim_not_called_again_on_double_click_replay(monkeypatch):
    spy = MagicMock(wraps=wrong_delivery_tools.submit_wrong_delivery_claim)
    monkeypatch.setattr(wrong_delivery_tools, "submit_wrong_delivery_claim", spy)

    config, action_id, action_type = _drive_wrong_delivery_to_confirmation("U-1002", "claim-double-click")

    confirm = Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}})
    v2_agent_graph.invoke(confirm, config=config)
    assert spy.call_count == 1

    v2_agent_graph.invoke(confirm, config=config)
    assert spy.call_count == 1


# --- declining never invokes the real function either ---


def test_declining_cancellation_never_invokes_the_real_function(monkeypatch):
    spy = MagicMock(wraps=cancellation_tools.submit_order_cancellation)
    monkeypatch.setattr(cancellation_tools, "submit_order_cancellation", spy)

    config, action_id, action_type = _drive_cancellation_to_confirmation("U-1004", "cancel-decline-spy")

    result = v2_agent_graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": False}}),
        config=config,
    )

    assert result["status"] == "FINAL"
    assert spy.call_count == 0
