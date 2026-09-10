# agent/v3/loop_safety.py
#
# Ported from v2/loop_safety.py — this machinery was hardened through real
# use and carries forward unchanged in logic. The only adaptation is
# consecutive_failure_count reading state["toolCallLog"] (V3's ordered
# log) instead of V2's toolLog — same record shape (toolName, error),
# same trailing-streak-from-the-most-recent-entry logic.

import concurrent.futures
import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, TypeVar

from v3.state import AgentStateV3

T = TypeVar("T")

MAX_LOOP_ITERATIONS = 8
MAX_REPEATED_IDENTICAL_CALLS = 2  # a 3rd identical (tool, args) call is rejected
MAX_RETRIES_PER_TOOL = 2  # a 3rd consecutive *failure* of the same tool escalates
LLM_TIMEOUT_SECONDS = 15
TOOL_TIMEOUT_SECONDS = 5


def tool_call_signature(tool_name: Optional[str], args: Dict[str, Any]) -> str:
    normalized = json.dumps(args or {}, sort_keys=True, default=str)
    return f"{tool_name}:{hashlib.sha256(normalized.encode()).hexdigest()}"


def is_repeated_call(
    state: AgentStateV3, tool_name: str, args: Dict[str, Any], workflow_stage: str
) -> bool:
    """
    True once the same (tool_name, args) pair has already been executed
    MAX_REPEATED_IDENTICAL_CALLS times WITHIN THE CURRENT WORKFLOW STAGE —
    scoped by stage, not the thread's entire lifetime, so a tool call
    legitimately re-run once the workflow has genuinely moved on (or a
    fresh capability entirely) is never blocked by a stale signature.
    """

    if state.get("_repeatedCallStage") != workflow_stage:
        return False

    signature = tool_call_signature(tool_name, args)
    signatures: List[str] = state.get("repeatedCallSignatures", [])

    return signatures.count(signature) >= MAX_REPEATED_IDENTICAL_CALLS


def record_call_signature(
    state: AgentStateV3, tool_name: str, args: Dict[str, Any], workflow_stage: str
) -> None:
    if state.get("_repeatedCallStage") != workflow_stage:
        state["repeatedCallSignatures"] = []
        state["_repeatedCallStage"] = workflow_stage

    signature = tool_call_signature(tool_name, args)
    state.setdefault("repeatedCallSignatures", []).append(signature)


def consecutive_failure_count(state: AgentStateV3, tool_name: str) -> int:
    """
    Trailing consecutive failures of this TOOL NAME specifically — a
    different, deliberately looser signal than is_repeated_call (name
    only, not exact args; stops at the first success/unrelated call
    scanning backward from the most recent entry).
    """

    count = 0

    for entry in reversed(state.get("toolCallLog", [])):
        if entry.get("toolName") != tool_name:
            break
        if not entry.get("error"):
            break
        count += 1

    return count


def iteration_budget_exceeded(state: AgentStateV3) -> bool:
    return state.get("loopIteration", 0) >= MAX_LOOP_ITERATIONS


def run_with_timeout(fn: Callable[[], T], timeout_seconds: float) -> T:
    """
    Wraps a synchronous call with a wall-clock timeout. Thread-pool based
    (not signal-based alarms) since this project's dev environment is
    Windows, where signal alarms don't work.
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        return future.result(timeout=timeout_seconds)


def escalate(state: AgentStateV3, reason: str) -> AgentStateV3:
    """Shared escalation path — always produces a graceful, deterministic message, never an LLM decision."""

    state["_escalationReason"] = reason
    state["_decision"] = {
        "action": "FINISH",
        "message": (
            "I wasn't able to fully resolve this automatically — let me "
            "connect you with a specialist who can help further."
        ),
        "toolName": None,
        "toolArgs": {},
        "uiProposal": [],
    }
    state["status"] = "ERROR"

    return state
