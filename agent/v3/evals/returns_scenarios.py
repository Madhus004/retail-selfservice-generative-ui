# agent/v3/evals/returns_scenarios.py
#
# Scripted scenarios for RETURNS — same spirit as
# cancellation_scenarios.py. Run on the deterministic path (no
# OPENAI_API_KEY needed) since the multi-stage ask flow and propose/
# confirm/execute cycle is what's worth continuously verifying.

import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from v3.graph import build_graph


@dataclass
class Scenario:
    name: str
    description: str
    run: Callable[[], None]


def _config(thread_id: str, run_id: str) -> Dict[str, str]:
    return {"configurable": {"thread_id": thread_id, "run_id": run_id}}


def _fresh_graph():
    return build_graph().compile(checkpointer=InMemorySaver())


def _resolve_to_confirmation(graph, thread_id: str, order_number: str):
    result = graph.invoke(
        {"messages": [HumanMessage(content=f"I want to return order {order_number}.")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )
    interrupt_value = result["__interrupt__"][0].value
    run_counter = 2

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

        result = graph.invoke(
            Command(resume={"type": interaction_type, "payload": payload}),
            config=_config(thread_id, f"run-{run_counter}"),
        )
        interrupt_value = result["__interrupt__"][0].value
        run_counter += 1

    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"
    return interrupt_value["actionId"], interrupt_value["actionType"], run_counter


def full_return_cycle_computes_refund_and_completes() -> None:
    graph = _fresh_graph()
    thread_id = f"eval-returns-full-cycle-{uuid.uuid4().hex[:8]}"

    action_id, action_type, run_counter = _resolve_to_confirmation(graph, thread_id, "U-1001")

    final = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id, f"run-{run_counter}"),
    )

    assert final["status"] == "FINAL"
    assert final["pendingAction"]["executed"] is True
    assert final["toolCallLog"][-1]["resultSummary"]["refundEstimate"] > 0


def ineligible_order_never_reaches_a_confirmation_screen() -> None:
    graph = _fresh_graph()
    thread_id = f"eval-returns-ineligible-{uuid.uuid4().hex[:8]}"

    result = graph.invoke(
        {"messages": [HumanMessage(content="I want to return order U-1003.")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )

    assert "__interrupt__" not in result
    assert result["status"] == "FINAL"
    assert result.get("pendingAction") is None


SCENARIOS: List[Scenario] = [
    Scenario(
        "full_return_cycle_computes_refund_and_completes",
        "A full order/item/reason/method walkthrough reaches confirmation and completes with a real refund estimate",
        full_return_cycle_computes_refund_and_completes,
    ),
    Scenario(
        "ineligible_order_never_reaches_a_confirmation_screen",
        "An order that isn't return-eligible finishes with an honest explanation, never a confirmation screen",
        ineligible_order_never_reaches_a_confirmation_screen,
    ),
]


def run_all() -> None:
    for scenario in SCENARIOS:
        try:
            scenario.run()
        except AssertionError as exc:
            print(f"FAIL  {scenario.name}: {exc}")
            raise
        else:
            print(f"PASS  {scenario.name} — {scenario.description}")


if __name__ == "__main__":
    run_all()
