# agent/v3/evals/cancellation_scenarios.py
#
# Scripted scenarios for CANCELLATION — same spirit as
# order_status_scenarios.py. Run on the deterministic path (no
# OPENAI_API_KEY needed) since the propose/confirm/execute cycle itself is
# what's worth continuously verifying, not LLM phrasing.

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


def single_item_order_reaches_confirmation_and_completes() -> None:
    graph = _fresh_graph()
    # Unique per run (not a fixed string) — the SQLite idempotency store
    # persists across process runs, and deterministic_action_id is derived
    # from thread_id, so a fixed thread_id would collide with a PRIOR
    # run's already-recorded actionId on a second pytest invocation.
    thread_id = f"eval-cancellation-single-item-{uuid.uuid4().hex[:8]}"

    result = graph.invoke(
        {"messages": [HumanMessage(content="Cancel order U-1005")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )

    assert "__interrupt__" in result
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "CONFIRM_ACTION"

    action_id = interrupt_value["actionId"]
    action_type = interrupt_value["actionType"]

    final = graph.invoke(
        Command(resume={"confirmation": {"actionId": action_id, "actionType": action_type, "accepted": True}}),
        config=_config(thread_id, "run-2"),
    )

    assert final["status"] == "FINAL"
    assert final["pendingAction"]["executed"] is True


def declining_never_executes_and_never_re_proposes() -> None:
    graph = _fresh_graph()
    thread_id = f"eval-cancellation-decline-{uuid.uuid4().hex[:8]}"

    result = graph.invoke(
        {"messages": [HumanMessage(content="Cancel order U-1005")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )
    interrupt_value = result["__interrupt__"][0].value

    final = graph.invoke(
        Command(
            resume={
                "confirmation": {
                    "actionId": interrupt_value["actionId"],
                    "actionType": interrupt_value["actionType"],
                    "accepted": False,
                }
            }
        ),
        config=_config(thread_id, "run-2"),
    )

    assert final["status"] == "FINAL"
    assert "__interrupt__" not in final
    assert not any(r["toolName"] == "submit_order_cancellation_tool" for r in final["toolCallLog"])


SCENARIOS: List[Scenario] = [
    Scenario(
        "single_item_order_reaches_confirmation_and_completes",
        "A single-item cancellable order goes straight to a real CONFIRM_ACTION interrupt and completes on accept",
        single_item_order_reaches_confirmation_and_completes,
    ),
    Scenario(
        "declining_never_executes_and_never_re_proposes",
        "Declining a proposed cancellation never executes it and never re-proposes it on the same turn",
        declining_never_executes_and_never_re_proposes,
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
