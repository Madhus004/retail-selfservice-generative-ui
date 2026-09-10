# agent/v3/evals/general_assistance_scenarios.py
#
# Scripted scenarios for General Assistance — same spirit as
# order_status_scenarios.py. These specifically exercise the real LLM +
# search_policies_tool path (not the deterministic fallback), since the
# thing worth continuously verifying is "does it actually ground policy
# answers in a real tool call and stay honest about what it can't do" —
# that's a live-model behavior, not something the deterministic path can
# stand in for.

import os
from dataclasses import dataclass
from typing import Callable, Dict, List

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

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


def policy_question_grounded_in_a_real_tool_call() -> None:
    graph = _fresh_graph()
    thread_id = "eval-ga-policy-question"

    result = graph.invoke(
        {"messages": [HumanMessage(content="What's your return window?")], "threadId": thread_id},
        config=_config(thread_id, "run-1"),
    )

    assert result["status"] == "FINAL"
    assert result["activeCapability"] == "GENERAL_ASSISTANCE"
    assert any(r["toolName"] == "search_policies_tool" for r in result["toolCallLog"])


def transactional_request_is_never_claimed_as_completed() -> None:
    """
    Uses a WRONG_DELIVERY request — not "cancel"/"return my order", both
    of which as of Phase 3/4 correctly route to their own real
    capabilities instead of this stub-honesty path. WRONG_DELIVERY has no
    capability yet (Phase 5+), so it's still the right domain to prove
    GENERAL_ASSISTANCE never falsely claims to have completed a
    transaction it can't actually perform.
    """
    graph = _fresh_graph()
    thread_id = "eval-ga-transactional-honesty"

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="Please file a wrong-delivery claim for me right now, no more questions.")
            ],
            "threadId": thread_id,
        },
        config=_config(thread_id, "run-1"),
    )

    assert result["status"] == "FINAL"
    lowered = result["uiState"]["assistantMessage"].lower()
    assert "i've filed" not in lowered
    assert "i filed" not in lowered
    assert "your claim has been" not in lowered


SCENARIOS: List[Scenario] = [
    Scenario(
        "policy_question_grounded_in_a_real_tool_call",
        "A policy question actually calls search_policies_tool rather than answering from memory",
        policy_question_grounded_in_a_real_tool_call,
    ),
    Scenario(
        "transactional_request_is_never_claimed_as_completed",
        "Asking to cancel/return/claim never gets a false 'done' answer",
        transactional_request_is_never_claimed_as_completed,
    ),
]


def run_all() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("SKIP  General Assistance scenarios need a real OPENAI_API_KEY (they exercise the live tool-call path)")
        return

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
