# agent/v3/evals/order_status_scenarios.py
#
# Scripted, assertion-based scenario evals — cheap, deterministic, the
# "highest signal per dollar" layer of the observability/evals plan.
# Distinct from test_v3_order_status.py's unit-style tests: these are
# whole-conversation walkthroughs read top to bottom as a spec of what
# "correct behavior" means for this capability, runnable standalone
# (`python -m v3.evals.order_status_scenarios`) or picked up by pytest
# (test_v3_evals.py wraps each SCENARIO as its own test).
#
# LLM-as-judge and LangSmith Datasets/Evals are real, named options for
# later (see the plan) — not needed yet while scenarios can be asserted
# exactly against the deterministic path.

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from v3.graph import build_graph


@dataclass
class Scenario:
    name: str
    description: str
    run: Callable[[], None]


def _config(thread_id: str, run_id: str) -> Dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "run_id": run_id}}


def _fresh_graph():
    return build_graph().compile(checkpointer=InMemorySaver())


def wismo_happy_path() -> None:
    """
    "Where is my order?" -> multiple orders offered -> customer picks one
    -> a concrete, non-duplicating answer about exactly that order.
    """

    graph = _fresh_graph()
    thread_id = "eval-wismo-happy-path"

    turn1 = graph.invoke(
        {"messages": [HumanMessage(content="Where is my order?")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )
    assert "__interrupt__" in turn1, "expected an ASK_CUSTOMER interrupt for multiple orders"
    interrupt_value = turn1["__interrupt__"][0].value
    assert interrupt_value["interruptType"] == "ASK_CUSTOMER"
    order_numbers = interrupt_value["offeredCandidates"]["orderNumbers"]
    assert len(order_numbers) > 1, "scenario assumes the demo customer has multiple orders"

    picked = order_numbers[0]
    turn2 = graph.invoke(
        Command(resume={"type": "ORDER_SELECTED", "payload": {"orderNumber": picked}}),
        config=_config(thread_id, "run-2"),
    )

    assert turn2["status"] == "FINAL"
    assert turn2["uiState"]["uiMode"] == "OrderSummaryCard"
    assert turn2["toolCallLog"][-1]["argsSummary"] == {"order_number": picked}
    assert turn2["uiState"]["canvasData"]["selectedOrder"]["order"]["orderNumber"] == picked
    # The whole point of the fine-grained catalog: the chat message is a
    # short caption, the card carries the detail — not both.
    assert len(turn2["uiState"]["assistantMessage"]) < 200


def known_order_number_skips_the_ask() -> None:
    """A customer who already names the order gets a direct answer, no unnecessary ask."""

    graph = _fresh_graph()
    thread_id = "eval-known-order-number"

    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1003?")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )

    assert result["status"] == "FINAL"
    assert [r["toolName"] for r in result["toolCallLog"]] == ["get_order_status_tool"]
    assert result["toolCallLog"][0]["argsSummary"] == {"order_number": "U-1003"}


def switching_orders_never_answers_from_a_stale_cache() -> None:
    """
    Two order-status questions in one thread, same capability throughout —
    the second must be answered from a fresh lookup, never the first
    order's cached result. The exact regression a real bug was caught by
    while this eval suite was being written.
    """

    graph = _fresh_graph()
    thread_id = "eval-switching-orders"

    graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1002?")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is order U-1004?")], "threadId": thread_id},
        config=_config(thread_id, "run-2"),
    )

    assert result["status"] == "FINAL"
    assert result["toolCallLog"][-1]["argsSummary"] == {"order_number": "U-1004"}
    assert any(
        r["argsSummary"] == {"order_number": "U-1002"} for r in result["toolCallLog"]
    ), "the first order's tool call must still be present in the log, not overwritten"


SCENARIOS: List[Scenario] = [
    Scenario("wismo_happy_path", "Multi-order ask, structured resume, correct final answer", wismo_happy_path),
    Scenario("known_order_number_skips_the_ask", "Named order number goes straight to an answer", known_order_number_skips_the_ask),
    Scenario(
        "switching_orders_never_answers_from_a_stale_cache",
        "A second, different order in one thread is never answered from the first's cache",
        switching_orders_never_answers_from_a_stale_cache,
    ),
]


def run_all() -> None:
    import os

    os.environ.pop("OPENAI_API_KEY", None)  # deterministic path — exact, reproducible

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
