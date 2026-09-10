# agent/v2/loop_safety.py
#
# Formalizes the inline safeguards Phase 1-2 had directly in graph.py
# (MAX_LOOP_ITERATIONS) into their own module alongside repeated-call
# detection, per-tool retry limits, and timeouts (plan section 30).
# Confirmation replay protection lives in confirmation.py/idempotency.py
# (Phase 4) — those are the "checks (5)(6)(7)" the plan groups under this
# same umbrella but implements alongside the sensitive-tool machinery
# itself, not here.

import concurrent.futures
import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, TypeVar

from v2.state import AgentStateV2

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
    state: AgentStateV2, tool_name: str, args: Dict[str, Any], workflow_stage: str
) -> bool:
    """
    True once the same (tool_name, args) pair has already been executed
    MAX_REPEATED_IDENTICAL_CALLS times WITHIN THE CURRENT WORKFLOW STAGE
    (2026-08 workflow-stage fix) — the next (3rd) attempt should be
    short-circuited rather than actually invoked.

    Scoped by workflow_stage, not persisted for the thread's entire
    lifetime: a real bug was found where this list was never reset at
    all (not even on capability switch), so a tool call that succeeded
    once could permanently block that exact (name, args) pair for the
    rest of the conversation — including a legitimate re-call once the
    workflow has genuinely moved on (e.g. re-checking eligibility after
    the customer names a different order, or authoritative revalidation
    right before execution). See record_call_signature, which is what
    actually performs the reset the moment the stage changes.
    """

    if state.get("_repeatedCallStage") != workflow_stage:
        # A different stage than whatever repeatedCallSignatures was last
        # recorded against — nothing in THIS stage has been attempted yet.
        return False

    signature = tool_call_signature(tool_name, args)
    signatures: List[str] = state.get("repeatedCallSignatures", [])

    return signatures.count(signature) >= MAX_REPEATED_IDENTICAL_CALLS


def record_call_signature(
    state: AgentStateV2, tool_name: str, args: Dict[str, Any], workflow_stage: str
) -> None:
    if state.get("_repeatedCallStage") != workflow_stage:
        state["repeatedCallSignatures"] = []
        state["_repeatedCallStage"] = workflow_stage

    signature = tool_call_signature(tool_name, args)
    state.setdefault("repeatedCallSignatures", []).append(signature)


def consecutive_failure_count(state: AgentStateV2, tool_name: str) -> int:
    """
    Trailing consecutive failures of this TOOL NAME specifically —
    deliberately keyed on name only, not exact args, and deliberately a
    *trailing* streak (stops counting at the first success or unrelated
    call scanning backward from the most recent entry).

    This is intentionally a different signal from is_repeated_call, which
    is signature-exact (tool_name AND args) and fires after just 2
    occurrences regardless of success/failure: if retry-limit were also
    keyed on the exact signature, it would never actually fire, since
    is_repeated_call would always short-circuit the 3rd identical attempt
    first (the same threshold, the same signature). Keying retry-limit on
    tool name only makes it answer a genuinely different question — "does
    this tool keep failing no matter what I try?" — which is exactly what
    plan section 30 means by a persistently-erroring call that should stop
    being retried, as distinct from a redundant identical call.
    """

    count = 0

    for entry in reversed(state.get("toolLog", [])):
        if entry.get("toolName") != tool_name:
            break
        if not entry.get("error"):
            break
        count += 1

    return count


def iteration_budget_exceeded(state: AgentStateV2) -> bool:
    return state.get("loopIteration", 0) >= MAX_LOOP_ITERATIONS


def run_with_timeout(fn: Callable[[], T], timeout_seconds: float) -> T:
    """
    Wraps a synchronous call with a wall-clock timeout. Uses a thread pool
    rather than signal-based alarms since the latter don't work on Windows
    (this project's dev environment) — a timeout raises
    concurrent.futures.TimeoutError, which is a TimeoutError subclass and
    so is caught by the same broad `except Exception` callers already use
    for ordinary tool failures (plan section 30: "a timeout is treated
    identically to a tool failure").
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        return future.result(timeout=timeout_seconds)


def escalate(state: AgentStateV2, reason: str) -> AgentStateV2:
    """
    Shared escalation path (plan section 30) — always produces a graceful,
    deterministic customer-facing message and routes to finish. Never an
    LLM decision: the agent is never the one deciding it's stuck.
    """

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
