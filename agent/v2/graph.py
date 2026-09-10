# agent/v2/graph.py
#
# The one generic, capability-agnostic agent/tool loop.
#
# Phase 1: classify_capability -> agent_reason -> execute_tool -> finish,
# ORDER_STATUS only, no interrupts.
# Phase 2 added real interrupt()-based pausing (ask_customer), the
# InMemorySaver checkpointer, and enforce_capability_switch as the single
# owner of capability/pending-state transitions (plan sections 2.2, 18,
# 18a, 19).
# Phase 3 formalized loop safety into v2/loop_safety.py (iteration cap,
# repeated-call detection, per-tool retry limits, timeouts, a dedicated
# escalate node) and added real per-node trace records via
# v2/observability.py, replacing V1's cosmetic hardcoded progress list with
# traces tied to what the graph actually did (plan sections 29-30).
# Phase 4-6 added request_confirmation/confirmation.py/idempotency.py (the
# sensitive-tool confirmation cycle) and registered all four capabilities.
# Phase 7 (this revision) adds real unsupported_node/clarify_node terminal/
# redirect nodes — now that every real capability exists, UNSUPPORTED/
# CLARIFY are routed to their own dedicated handling instead of being
# clamped into ORDER_STATUS (plan sections 16-17) — plus the between-turns
# capability-switch path is now exercised by a real second capability
# rather than always degrading.
#
# Nothing here imports agent/graph.py (V1) or agent/state.py (V1).

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_config
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from fastapi import HTTPException

from tools import read_policy_file

from v2 import confirmation, idempotency, loop_safety
from v2.a2ui import build_mandatory_ui, validate_agent_a2ui
from v2.capabilities.registry import CAPABILITIES, get_capability
from v2.classifier import ClassificationContext, classify, extract_order_number
from v2.observability import Stopwatch, TraceRecord, emit, now_iso
from v2.state import AgentStateV2
from v2.tools.cancellation_tools import validate_cancellation_proposal
from v2.tools.returns_tools import build_return_preview
from v2.tools.wrong_delivery_tools import build_wrong_delivery_claim_preview

load_dotenv()

# PendingAction.actionType <-> the tool that actually performs it, and the
# capability-declared sensitive tool name that triggers confirmation for
# it. One entry per sensitive tool across all capabilities (Phase 4 adds
# CANCELLATION's; Phase 5-6 add their own rows here, nothing else changes).
_SENSITIVE_ACTION_TYPES = {
    "submit_order_cancellation_tool": "SUBMIT_CANCELLATION",
    "submit_wrong_delivery_claim_tool": "SUBMIT_WRONG_DELIVERY_CLAIM",
    "create_return_tool": "CREATE_RETURN",
}
_ACTION_TYPE_TO_TOOL_NAME = {v: k for k, v in _SENSITIVE_ACTION_TYPES.items()}

# The full set of structured-interaction types a resume can carry (2026-08
# structured-interaction fix). Used identically as (a) the value
# decision["interactionType"] declares when asking a question, (b) the
# interrupt payload's "expectedInteractionType", and (c) resumed["type"] —
# one canonical vocabulary end to end, so validating a resume is just an
# equality check against what was already declared when the question was
# asked, not a second inference.
InteractionType = Literal[
    "ORDER_SELECTED",
    "ITEM_SELECTED",
    "REASON_SELECTED",
    "RETURN_METHOD_SELECTED",
    "FREEFORM",
]

# Fixed options for RETURNS' reason stage — no tool call needed (there's no
# per-order variation), but still a single source of truth rather than
# duplicated between backend validation and frontend copy.
RETURN_REASON_OPTIONS = [
    "Wrong size/fit",
    "Changed my mind",
    "Defective/damaged",
    "Other",
]

# (capability name, interaction type) -> the A2UI component type proposed
# for that ask, whether the proposal comes from the LLM's ask_customer tool
# call (via its askType arg) or a deterministic capability function.
_ASK_TYPE_TO_A2UI: Dict[tuple, str] = {
    ("ORDER_STATUS", "ORDER_SELECTED"): "orderSelection",
    ("CANCELLATION", "ORDER_SELECTED"): "cancellationOrderSelection",
    ("CANCELLATION", "ITEM_SELECTED"): "cancellationItemSelection",
    ("RETURNS", "ORDER_SELECTED"): "orderSelection",
    ("RETURNS", "ITEM_SELECTED"): "returnItemSelection",
    ("RETURNS", "REASON_SELECTED"): "returnReasonPrompt",
    ("RETURNS", "RETURN_METHOD_SELECTED"): "returnMethodPrompt",
}


@tool
def finish(message: str) -> str:
    """Call this once you have enough information to give the customer
    their final answer for this turn. message is the concise, concrete
    customer-facing text — lead with the outcome, cite real data you
    already retrieved, no generic closing filler."""

    return message


@tool
def ask_customer(
    question: str,
    askType: InteractionType = "FREEFORM",
) -> str:
    """Call this when you need the customer to choose something or provide
    more information before you can continue. question is the concise
    customer-facing text. askType tells the UI what kind of structured
    picker to show alongside your question — set it to ORDER_SELECTED when
    asking which order, ITEM_SELECTED when asking which items/quantities,
    REASON_SELECTED when asking why (returns only),
    RETURN_METHOD_SELECTED when asking how to return something (mail vs
    in-store), or leave it as FREEFORM for anything else (e.g. asking for
    an order number as plain text). Getting this right matters: it decides
    what interactive UI the customer actually sees, not just your
    question's wording."""

    return question


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize(value: Any) -> Any:
    # Structured tool results, not raw LLM prose — safe to store/trace as-is
    # per the privacy stance in v2/observability.py.
    return value


def _current_run_id() -> str:
    """
    runId is deliberately NOT a graph-state channel (2026-08 runId/threadId
    fix) — it's a per-HTTP-invocation identity, not conversation state.
    Every node in this file does `state[...] = ...; return state`, echoing
    the WHOLE state dict on every return; combined with the router passing
    a fresh runId via Command(update={"runId": ...}) on every resume, that
    made every resume a genuine double-write to the same channel in one
    step (LangGraph's InvalidUpdateError: "Can receive only one value per
    step"), confirmed via an isolated minimal-graph repro. get_config() —
    LangGraph's contextvar-based accessor for the CURRENT invocation's
    RunnableConfig — reads the per-call value the router now threads
    through config["configurable"]["run_id"] instead, without needing a
    config parameter on every node function or _emit() call site, and
    without ever touching a checkpointed channel.
    """

    try:
        run_id = (get_config().get("configurable") or {}).get("run_id")
    except RuntimeError:
        # get_config() raises outside a LangGraph run (e.g. a node function
        # unit-tested by calling it directly, config=None) — fall back
        # rather than crash a pattern several existing tests already rely on.
        run_id = None

    return run_id or "unknown"


def _emit(state: AgentStateV2, **kwargs: Any) -> None:
    """Small convenience wrapper so node code doesn't repeat runId/sessionId/
    workflowStage boilerplate on every emit() call."""

    emit(
        TraceRecord(
            runId=_current_run_id(),
            sessionId=state.get("threadId"),
            ts=now_iso(),
            loopIteration=state.get("loopIteration", 0),
            activeCapability=state.get("activeCapability"),
            workflowStage=_compute_workflow_stage(state),
            **kwargs,
        )
    )


def _build_canvas_data(state: AgentStateV2) -> Dict[str, Any]:
    tool_results = state.get("toolResults", {})
    canvas_data: Dict[str, Any] = {}

    recent = tool_results.get("get_recent_orders_tool")
    if isinstance(recent, dict):
        canvas_data["customer"] = recent.get("customer")
        canvas_data["orders"] = recent.get("orders")

    # RETURNS' own eligible-orders listing (2026-08 structured-interaction
    # fix) reuses the "orders" key too — same orderSelection A2UI type,
    # same frontend mapping, just pre-filtered to return-eligible orders
    # only, unlike get_recent_orders_tool above.
    return_eligible_orders = tool_results.get("get_return_eligible_orders_tool")
    if isinstance(return_eligible_orders, dict):
        canvas_data["customer"] = return_eligible_orders.get("customer", canvas_data.get("customer"))
        canvas_data["orders"] = return_eligible_orders.get("orders")

    eligible = tool_results.get("get_cancellation_eligible_orders_tool")
    if isinstance(eligible, dict):
        canvas_data["customer"] = eligible.get("customer", canvas_data.get("customer"))
        canvas_data["eligibleOrders"] = eligible.get("orders")

    dashboard = tool_results.get("get_order_status_tool")
    if isinstance(dashboard, dict):
        canvas_data["customer"] = dashboard.get("customer", canvas_data.get("customer"))
        canvas_data["selectedOrder"] = dashboard

    return_eligibility = tool_results.get("get_return_eligible_items_tool")
    if isinstance(return_eligibility, dict):
        # Feeds the "returnItemSelection" A2UI type's frontend rendering
        # (Phase 8) — nothing before this read it, so it had no canvasData
        # entry until now.
        canvas_data["returnEligibility"] = return_eligibility

        if return_eligibility.get("eligible"):
            # Single source of truth for the reason-prompt stage's options
            # (2026-08 structured-interaction fix) — not duplicated in
            # frontend copy.
            canvas_data["returnReasonOptions"] = RETURN_REASON_OPTIONS

    return canvas_data


def _compute_offered_candidates(state: AgentStateV2) -> Dict[str, Any]:
    """
    What ask_customer is about to offer THIS turn, recomputed fresh from
    toolResults rather than persisted-then-trusted (plan section 18a,
    correction 3 — the client is not a security boundary even for
    unambiguous button-generated input; see AgentStateV2's own note on why
    there's no persisted "offered candidates" field). Generalized (2026-08
    structured-interaction fix) beyond just order numbers to cover every
    structured selection type a resume can carry:

    {
      "orderNumbers": [...],
      "items": {"<orderLineId>": {"maxQuantity": int}, ...}  # for the
          CURRENTLY SELECTED order only, per _resolve_order_number
      "reasons": [...],
      "methods": [...],
    }

    Each key is populated only when the relevant toolResult (and, for
    items/methods, a resolved order number) is actually present — an
    absent key means that interaction type has nothing valid to offer
    right now, and any resume claiming it should be rejected.
    """

    tool_results = state.get("toolResults", {})
    candidates: Dict[str, Any] = {}
    order_numbers: List[str] = []

    # Checked in order — whichever order-bearing tool this capability
    # actually called is the one whose result was (or is about to be)
    # offered. Each capability that lists its own orders adds one entry
    # here, never a change to the entries already present.
    for tool_name in (
        "get_recent_orders_tool",
        "get_cancellation_eligible_orders_tool",
        "get_return_eligible_orders_tool",
    ):
        source = tool_results.get(tool_name)
        if isinstance(source, dict) and source.get("orders"):
            order_numbers = [
                order.get("orderNumber")
                for order in source["orders"]
                if isinstance(order, dict) and order.get("orderNumber")
            ]
            break

    candidates["orderNumbers"] = order_numbers

    order_number = _resolve_order_number(state)

    eligible_orders = (tool_results.get("get_cancellation_eligible_orders_tool") or {}).get("orders") or []
    selected_cancellation_order = next(
        (o for o in eligible_orders if o.get("orderNumber") == order_number), None
    )
    if selected_cancellation_order:
        candidates["items"] = {
            item["orderLineId"]: {"maxQuantity": item.get("cancellableQuantity", 0)}
            for item in selected_cancellation_order.get("items", [])
        }

    return_eligibility = tool_results.get("get_return_eligible_items_tool")
    if isinstance(return_eligibility, dict) and return_eligibility.get("eligible"):
        candidates["items"] = {
            item["orderLineId"]: {"maxQuantity": item.get("returnableQuantity", 0)}
            for item in return_eligibility.get("items", [])
        }
        candidates["reasons"] = list(RETURN_REASON_OPTIONS)
        candidates["methods"] = list(return_eligibility.get("returnMethods") or [])

    return candidates


# ---------------------------------------------------------------------------
# classify_capability — fresh-turn classification only. No longer decides
# activeCapability itself (Phase 1 did, as a temporary shortcut) —
# enforce_capability_switch is now the single owner of that decision, for
# both fresh turns and pivots forwarded from an interrupted node.
# ---------------------------------------------------------------------------


def classify_capability_node(state: AgentStateV2) -> AgentStateV2:
    stopwatch = Stopwatch()
    # Snapshot prior turns BEFORE recording this one — recentTurnsSummary is
    # meant as "what came before", not an echo of the current message that
    # classify()'s own first argument already carries.
    context = ClassificationContext(
        activeCapability=state.get("activeCapability"),
        pendingQuestionSummary=None,
        recentTurnsSummary=_recent_turns_as_text(state),
    )
    _record_conversation_turn(state, "user", state.get("userMessage", ""))
    classification = classify(state["userMessage"], context)
    state["_classification"] = classification.model_dump()

    _emit(
        state,
        agentAction="CLASSIFY",
        latencyMs=stopwatch.elapsed_ms(),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini") if os.getenv("OPENAI_API_KEY") else "deterministic-fallback",
    )

    return state


def enforce_capability_switch_node(state: AgentStateV2) -> AgentStateV2:
    """
    Single owner of every capability/pending-state transition (plan section
    18a, correction 2). Reads a classification from EITHER _classification
    (set by classify_capability on a fresh turn) OR _pendingPivot (forwarded
    by an interrupted node after detecting __abandon__) — never both, and
    the interrupted nodes themselves never touch pendingAction/toolResults/
    activeCapability directly.
    """

    pending_pivot = state.get("_pendingPivot")

    if pending_pivot:
        classification = pending_pivot.get("classification") or {}
        state["userMessage"] = pending_pivot.get("newMessage", state.get("userMessage", ""))
        # Refresh _classification from the pivot's own verdict — without
        # this, downstream order-number resolution (_resolve_order_number,
        # every deterministic capability function, the LLM prompt's tool-
        # result hinting) would keep reading whatever classification was
        # set BEFORE the pivot, silently using a stale (and possibly
        # wrong-capability) orderNumber for the rest of this turn.
        state["_classification"] = classification
        state["_pendingPivot"] = None
        # A pivot forwarded from an interrupted node is, by construction,
        # always a genuine switch attempt — that's the only reason the
        # router ever sends __abandon__ in the first place.
        is_switch_attempt = True
    else:
        classification = state.get("_classification") or {}
        is_switch_attempt = bool(classification.get("isCapabilitySwitch"))

    requested_capability = classification.get("capability") or "ORDER_STATUS"
    old_capability = state.get("activeCapability")

    # Phase 7: all four real capabilities are registered, and UNSUPPORTED/
    # CLARIFY are legitimate destinations in their own right (routed by
    # route_after_capability_switch to their own dedicated nodes below,
    # never into agent_reason's get_capability() lookup) — so the
    # classified/forwarded capability is used directly, with no clamp.
    effective_capability = requested_capability

    switched = bool(old_capability) and (
        is_switch_attempt or effective_capability != old_capability
    )

    if switched:
        pending_action = state.get("pendingAction")
        cleared = False

        if pending_action and not pending_action.get("consumed") and not pending_action.get("executed"):
            state.setdefault("archivedPendingActions", []).append(pending_action)
            state["pendingAction"] = None
            cleared = True

        state["previousCapability"] = old_capability
        state["capabilityTransition"] = {
            "from": old_capability,
            "to": effective_capability,
            "requestedCapability": requested_capability,
            "clearedPending": cleared,
        }
        state["toolResults"] = {}
        state["loopIteration"] = 0
        state["clarifyAttempts"] = 0
        # Structured-selection scratch state is capability-specific (an
        # ITEM_SELECTED payload's orderLineIds only mean something for the
        # order/capability they were validated against) — must be cleared
        # on every switch exactly like toolResults/pendingAction, or a
        # stale selection from the abandoned capability can silently be
        # reused by the new one. Caught via a real bug: RETURNS'
        # _selectedLineItems (U-1001's line ids) survived a pivot to
        # CANCELLATION and were fed straight into
        # submit_order_cancellation_tool for U-1004, failing validation
        # every retry until escalation.
        state["_selectedLineItems"] = None
        state["_selectedReason"] = None
        state["_selectedReturnMethod"] = None
    else:
        state["capabilityTransition"] = None

    state["activeCapability"] = effective_capability
    state.setdefault("toolLog", [])
    state.setdefault("toolResults", {})
    state.setdefault("loopIteration", 0)

    if switched:
        _emit(
            state,
            agentAction="SWITCH",
            capabilityTransition=state["capabilityTransition"],
        )

    return state


def route_after_capability_switch(state: AgentStateV2) -> str:
    """
    UNSUPPORTED/CLARIFY are real, terminal-shaped destinations (plan
    sections 16-17), never bound to a capability's tools — routed to their
    own dedicated nodes here so agent_reason's get_capability() lookup
    never has to handle them.
    """

    capability = state.get("activeCapability")

    if capability == "UNSUPPORTED":
        return "unsupported"
    if capability == "CLARIFY":
        return "clarify"

    return "agent_reason"


_UNSUPPORTED_MESSAGE = (
    "I'm not able to help with that here — I can help with order status, "
    "returns, cancellations, or delivery issues. Is there something along "
    "those lines I can help with?"
)


def unsupported_node(state: AgentStateV2) -> AgentStateV2:
    """
    Deterministic terminal node (plan section 16) — a real support request,
    just not one of the four capabilities this agent can act on. Never an
    LLM call, so the honest "I can't help with that here" response can't be
    talked around. Builds the final uiState/status directly and ends the
    turn (bypassing finish_node, which is for capability-scoped turns) —
    the thread stays alive, so the next free-form message re-enters
    classify_capability fresh, unaffected by this one.
    """

    components = [{"type": "welcome", "props": {}, "dataKey": None}]

    state["a2uiComponents"] = components
    state["a2uiOrigin"] = "MANDATORY_DETERMINISTIC"
    state["uiState"] = {
        "uiMode": "welcome",
        "assistantMessage": _UNSUPPORTED_MESSAGE,
        "canvasData": {},
        "a2ui": components,
        # Contextual next steps attached to THIS turn (2026-08 fix) — the
        # replacement for the permanent "Choose a support option" panel
        # this project's frontend used to show for the whole conversation.
        # Same idea V1 already uses suggestedReplies for (agent/graph.py),
        # just reached from a different node here since UNSUPPORTED is
        # exactly the "customer hasn't found their footing yet" moment
        # those starter options are actually useful.
        "suggestedReplies": [
            "Where is my order?",
            "Return an item",
            "Cancel an order",
            "I received the wrong item",
        ],
    }
    state["status"] = "UNSUPPORTED"

    _record_conversation_turn(state, "assistant", _UNSUPPORTED_MESSAGE)
    _emit(state, agentAction="FINISH", a2uiOrigin="MANDATORY_DETERMINISTIC", finalOutcome="UNSUPPORTED")

    return state


_CLARIFY_QUESTION = (
    "I want to make sure I help with the right thing — are you asking "
    "about an order's status, a return, a cancellation, or a delivery "
    "issue?"
)


def clarify_node(state: AgentStateV2) -> AgentStateV2:
    """
    Deterministic redirect (plan section 17) — not enough signal yet to
    pick a capability. Functionally the same shape as "not enough signal to
    proceed", so it asks via a real ask_customer interrupt rather than
    being its own dead end. Capped at 2 consecutive attempts with no
    capability ever established in this thread (enforce_capability_switch
    only resets clarifyAttempts when the capability actually changes, so
    consecutive CLARIFY-to-CLARIFY turns keep accumulating here) — a 3rd
    bounces to the shared bounded-effort escalation instead of asking
    indefinitely.
    """

    attempts = state.get("clarifyAttempts", 0) + 1
    state["clarifyAttempts"] = attempts

    if attempts > 2:
        loop_safety.escalate(state, "clarify_attempts_exceeded")
        return state

    state["_decision"] = {
        "action": "ASK_CUSTOMER",
        "message": _CLARIFY_QUESTION,
        "toolName": None,
        "toolArgs": {},
        "uiProposal": [],
    }
    _record_conversation_turn(state, "assistant", _CLARIFY_QUESTION)

    return state


def route_after_clarify(state: AgentStateV2) -> str:
    if state.get("_escalationReason"):
        return "escalate"

    return "ask_customer"


def _policy_text_for(capability) -> str:
    # Policy-file selection is deterministic and capability-scoped (plan
    # section 9-10) — pre-seeded into the prompt rather than exposed as an
    # agent-callable tool, the same way V1's retrieve_policy_node pre-loads
    # policy text before generate_explanation_node runs. Reuses V1's own
    # file-reading helper directly (content, not orchestration — plan
    # section 5) rather than duplicating it.
    contents = [read_policy_file(name) for name in capability.policy_files]
    return "\n\n---\n\n".join(text for text in contents if text)


# "small role/content log, not full raw transcript" (plan section 7) — kept
# short on purpose: this is context for the model, not an audit trail (the
# trace store already serves that role). ~6 exchanges is enough for a
# customer to reference something they said a couple of turns ago without
# ballooning every prompt.
_MAX_CONVERSATION_TURNS = 12


def _record_conversation_turn(state: AgentStateV2, role: str, content: str) -> None:
    """
    Appends to conversationSummary — actual, working conversation memory
    (2026-08 conversation-memory fix). This field existed in AgentStateV2
    since Phase 0 specifically for this purpose but was never wired up:
    nothing ever read or wrote it, so neither the classifier nor
    agent_reason's LLM calls had any visibility into what was said in
    earlier turns, only a handful of narrow structured fields
    (activeCapability, toolResults, lastKnownOrderNumber, the selection
    scratch fields). That's what made "which order are we working on?"
    asked mid-flow go nowhere — there was no memory to answer it from, and
    a mandatory-stage ask has no other channel for free text (see
    ask_customer_node).

    Persisted for free via the same LangGraph checkpoint that already
    carries toolLog/toolResults/pendingAction across turns — this is a
    plain list append, not a separate store, and needs no extra LLM call.
    """

    if not content:
        return

    turns = state.setdefault("conversationSummary", [])

    # Idempotent by design — several exit points (agent_reason_node's own
    # FINISH branches, finish_node's catch-all below for paths like
    # loop_safety.escalate() that bypass agent_reason_node entirely) can
    # legitimately try to record the same message; only the first sticks.
    if turns and turns[-1] == {"role": role, "content": content}:
        return

    turns.append({"role": role, "content": content})

    if len(turns) > _MAX_CONVERSATION_TURNS:
        del turns[: len(turns) - _MAX_CONVERSATION_TURNS]


def _recent_turns_as_text(state: AgentStateV2) -> List[str]:
    """
    conversationSummary formatted as short "role: content" strings — the
    shape classifier.ClassificationContext.recentTurnsSummary already
    expects (it was declared for this from the start, just never fed
    anything real; see classify_capability_node/router.py).
    """

    return [f"{turn['role']}: {turn['content']}" for turn in state.get("conversationSummary", [])]


def _build_messages(state: AgentStateV2, capability) -> List:
    tool_results = state.get("toolResults", {})

    system_text = capability.system_prompt
    policy_text = _policy_text_for(capability)
    if policy_text:
        system_text += (
            "\n\nRelevant policy, for your own reasoning only — never quote "
            "internal policy mechanics to the customer:\n" + policy_text
        )

    messages: List = [SystemMessage(system_text)]

    # Prior turns this session, so the model can answer something the
    # customer references from a couple of turns back ("the order I asked
    # about earlier") instead of only ever seeing this single message in
    # isolation (2026-08 conversation-memory fix).
    for turn in state.get("conversationSummary", []):
        if turn["role"] == "assistant":
            messages.append(AIMessage(turn["content"]))
        else:
            messages.append(HumanMessage(turn["content"]))

    human_text = f"Customer message: {state['userMessage']}"

    if tool_results:
        human_text += "\n\nTool results so far this turn:\n" + json.dumps(
            tool_results, default=str
        )
    elif (
        state.get("capabilityTransition")
        and state["capabilityTransition"].get("from") != state["capabilityTransition"].get("to")
        and state.get("lastKnownOrderNumber")
    ):
        # First turn right after a GENUINE cross-capability switch, nothing
        # looked up yet this turn — surface the order the customer was just
        # looking at as a hint only (plan walkthrough F), not a fact to
        # assert; the agent still calls its own tools to confirm anything
        # about it. The from != to check (2026-08 fix) is what keeps this
        # from firing when the "transition" is same-capability (e.g. the
        # customer clicked "Track a different order" right after an
        # ORDER_STATUS answer) — that case means the opposite of "still
        # relevant," and this hint was previously talking the model into
        # re-answering about the same order the customer just asked to move
        # on from.
        human_text += (
            f"\n\n(The customer was just looking at order "
            f"{state['lastKnownOrderNumber']} before this — likely still "
            "relevant if this message doesn't name a different order.)"
        )

    messages.append(HumanMessage(human_text))
    return messages


def _resolve_order_number(state: AgentStateV2) -> Any:
    """
    Order number for the current turn's deterministic reasoning: the
    classifier's extraction, else a regex match on the raw message, else —
    only on the very first turn right after a capability switch (never
    mid-capability, so an unrelated "what about my other order?" still
    lists orders normally rather than silently reusing a stale one) — the
    last order any tool call actually resolved this session. That fallback
    is what lets a switch like "Where is order U-1002?" -> "It says
    delivered but I never got it." carry the order across capabilities
    instead of re-asking (plan walkthrough F) — the concrete gap V1's
    stateless, single-call design can't close.
    """

    classification = state.get("_classification") or {}
    order_number = classification.get("orderNumber") or extract_order_number(
        state.get("userMessage", "")
    )

    transition = state.get("capabilityTransition")
    # A GENUINE cross-capability transition only — "capabilityTransition is
    # truthy" alone isn't enough (2026-08 fix): enforce_capability_switch_
    # node also sets it when the classifier flags isCapabilitySwitch=True
    # for a message that stays in the SAME capability (e.g. "Track a
    # different order" clicked right after answering about one order) —
    # that's exactly the "unrelated ask, mid-capability" case this
    # function's own docstring says must list orders fresh, not silently
    # reuse the last one. A same-capability "transition" carries no cross-
    # capability order-continuity intent at all.
    if not order_number and transition and transition.get("from") != transition.get("to"):
        order_number = state.get("lastKnownOrderNumber")

    return order_number


# ---------------------------------------------------------------------------
# Workflow-stage derivation (2026-08 workflow-stage fix). One small, pure
# function per capability, each mirroring the EXACT same conditions its own
# _deterministic_<capability> function already branches on below — not a
# second, independently-maintained decision tree, just a cheap classification
# of "which of those branches would fire right now" for two purposes:
#   1. agent_reason_node's deterministic gate (a handful of these stages are
#      MANDATORY — never left to the LLM's own ask-vs-finish/tool judgment);
#   2. every trace record's workflowStage field (via _emit), and loop_safety's
#      per-stage repeated-call scoping (via execute_tool_node) — both derived
#      fresh from state, never persisted as their own source of truth.
# ---------------------------------------------------------------------------


def _order_status_stage(state: AgentStateV2) -> str:
    tool_results = state.get("toolResults", {})

    if "get_order_status_tool" in tool_results:
        return "READY_TO_ANSWER"

    if _resolve_order_number(state):
        return "NEED_STATUS_LOOKUP"

    recent = tool_results.get("get_recent_orders_tool")

    if recent:
        orders = recent.get("orders") or []
        if len(orders) > 1:
            return "WAITING_FOR_ORDER_SELECTION"
        return "NEED_STATUS_LOOKUP"

    return "NEED_ORDER_FETCH"


def _cancellation_stage(state: AgentStateV2) -> str:
    tool_results = state.get("toolResults", {})
    eligible = tool_results.get("get_cancellation_eligible_orders_tool")

    if not eligible:
        return "ELIGIBILITY_REQUIRED"

    orders = (eligible or {}).get("orders") or []

    if not orders:
        return "NO_ELIGIBLE_ORDERS"

    order_number = _resolve_order_number(state)
    selected_order = next((o for o in orders if o.get("orderNumber") == order_number), None)

    if not selected_order:
        if len(orders) == 1:
            selected_order = orders[0]
        else:
            return "WAITING_FOR_ORDER_SELECTION"

    cancellable_items = [
        item for item in selected_order.get("items", []) if item.get("cancellableQuantity", 0) > 0
    ]

    if not cancellable_items:
        return "NOTHING_LEFT_TO_CANCEL"

    if state.get("_selectedLineItems") is None and len(cancellable_items) > 1:
        return "WAITING_FOR_ITEM_SELECTION"

    return "READY_TO_PROPOSE"


def _returns_stage(state: AgentStateV2) -> str:
    tool_results = state.get("toolResults", {})
    eligibility = tool_results.get("get_return_eligible_items_tool")

    if not eligibility:
        order_number = _resolve_order_number(state)
        if order_number:
            return "NEED_ELIGIBILITY_CHECK"

        eligible_orders_result = tool_results.get("get_return_eligible_orders_tool")
        if not eligible_orders_result:
            return "NEED_ORDER_FETCH"

        orders = (eligible_orders_result or {}).get("orders") or []
        if len(orders) > 1:
            return "WAITING_FOR_ORDER_SELECTION"
        if not orders:
            return "NO_ELIGIBLE_ORDERS"
        return "NEED_ELIGIBILITY_CHECK"

    if not eligibility.get("eligible"):
        return "INELIGIBLE"

    returnable_items = [
        item for item in (eligibility.get("items") or []) if item.get("returnableQuantity", 0) > 0
    ]

    if not returnable_items:
        return "NOTHING_LEFT_TO_RETURN"

    if state.get("_selectedLineItems") is None and len(returnable_items) > 1:
        return "WAITING_FOR_ITEM_SELECTION"

    if state.get("_selectedReason") is None:
        return "WAITING_FOR_REASON"

    available_methods = eligibility.get("returnMethods") or []
    if state.get("_selectedReturnMethod") is None and len(available_methods) > 1:
        return "WAITING_FOR_METHOD"

    return "READY_TO_PROPOSE"


def _wrong_delivery_stage(state: AgentStateV2) -> str:
    tool_results = state.get("toolResults", {})

    if "get_order_status_tool" not in tool_results:
        return "NEED_STATUS_LOOKUP" if _resolve_order_number(state) else "NEED_ORDER_NUMBER"

    return "READY_TO_PROPOSE"


# Stages where the next ask is UNAMBIGUOUS — a required, enumerable
# structured choice with no genuine judgment call to make — so it must
# never be left to the LLM's own ask-vs-finish/tool decision (plan
# principle carried into this fix: deterministic orchestration owns
# structured UI selections; the LLM owns everything genuinely ambiguous).
# Deliberately NOT included: the "which tool do I need first" stages
# (ELIGIBILITY_REQUIRED, NEED_ORDER_FETCH, NEED_STATUS_LOOKUP, ...) and
# READY_TO_PROPOSE — both stay LLM-driven, since the LLM may have already
# resolved them from free text (e.g. "cancel the hoodie on U-1004, wrong
# size" gives order+items+reason in one message) and forcing another
# ask there would fight the customer's own message instead of using it.
_MANDATORY_ASK_STAGES = {
    "WAITING_FOR_ORDER_SELECTION",
    "WAITING_FOR_ITEM_SELECTION",
    "WAITING_FOR_REASON",
    "WAITING_FOR_METHOD",
}


def _compute_workflow_stage(state: AgentStateV2) -> str:
    """
    Derived fresh from state every time, never persisted — mirrors
    _compute_offered_candidates' own "recompute, don't trust a stale
    field" discipline. Defensively coded (never raises): this feeds every
    trace record via _emit, so a bug here must never take down the actual
    graph execution it's merely describing.
    """

    try:
        pending = state.get("pendingAction")
        capability_name = state.get("activeCapability")

        # A pendingAction only reflects the CURRENT capability's in-flight
        # action. enforce_capability_switch_node deliberately leaves an
        # already-executed pendingAction in place across a switch (it only
        # archives/clears one that's still unconsumed) — so after a switch,
        # state["pendingAction"] can be a finished action belonging to the
        # PREVIOUS capability. Without this guard, that stale action made
        # every workflow stage compute as "COMPLETED" regardless of what
        # the new capability was actually doing, which silently disabled
        # the mandatory-ask gate for the rest of that thread (a real bug:
        # RETURNS reached FINISH with an ungated LLM decision, producing an
        # incoherent prose response, right after a prior CANCELLATION had
        # completed in the same thread).
        if pending and pending.get("capability") == capability_name:
            if pending.get("executed"):
                return "COMPLETED"
            if not pending.get("consumed"):
                return "WAITING_FOR_CONFIRMATION"

        if capability_name == "ORDER_STATUS":
            return _order_status_stage(state)
        if capability_name == "CANCELLATION":
            return _cancellation_stage(state)
        if capability_name == "RETURNS":
            return _returns_stage(state)
        if capability_name == "WRONG_DELIVERY":
            return _wrong_delivery_stage(state)

        return capability_name or "UNKNOWN"
    except Exception:  # noqa: BLE001 - observability must never crash the graph it's describing
        return "UNKNOWN"


def _deterministic_order_status(state: AgentStateV2) -> AgentStateV2:
    tool_results = state.get("toolResults", {})
    order_number = _resolve_order_number(state)

    if "get_order_status_tool" in tool_results:
        dashboard = tool_results["get_order_status_tool"] or {}
        summary = dashboard.get("summary", {}) if isinstance(dashboard, dict) else {}
        message = summary.get("customerMessage") or "Here's the latest status for your order."
        state["_decision"] = {
            "action": "FINISH",
            "message": message,
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    if order_number:
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_order_status_tool",
            "toolArgs": {"order_number": order_number},
            "message": "",
            "uiProposal": [],
        }
        return state

    if "get_recent_orders_tool" in tool_results:
        state["_decision"] = {
            "action": "ASK_CUSTOMER",
            "message": "I found a few recent orders — which one would you like to check?",
            "toolName": None,
            "toolArgs": {},
            "interactionType": "ORDER_SELECTED",
            "uiProposal": [
                {"type": "orderSelection", "props": {}, "dataKey": "get_recent_orders_tool"}
            ],
        }
        return state

    state["_decision"] = {
        "action": "CALL_TOOL",
        "toolName": "get_recent_orders_tool",
        "toolArgs": {},
        "message": "",
        "uiProposal": [],
    }
    return state


def _deterministic_cancellation(state: AgentStateV2) -> AgentStateV2:
    tool_results = state.get("toolResults", {})

    if state.get("_confirmationDeclined"):
        state["_confirmationDeclined"] = False
        state["_decision"] = {
            "action": "FINISH",
            "message": "No problem — I won't cancel that. Anything else I can help with?",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    eligible = tool_results.get("get_cancellation_eligible_orders_tool")

    if not eligible:
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_cancellation_eligible_orders_tool",
            "toolArgs": {},
            "message": "",
            "uiProposal": [],
        }
        return state

    orders = (eligible or {}).get("orders") or []

    if not orders:
        state["_decision"] = {
            "action": "FINISH",
            "message": "I don't see any orders that are still eligible to cancel — once an order ships, it can no longer be cancelled here.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    order_number = _resolve_order_number(state)
    selected_order = next((o for o in orders if o.get("orderNumber") == order_number), None)

    if not selected_order:
        if len(orders) == 1:
            selected_order = orders[0]
        else:
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                "message": "Which order would you like to cancel?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "ORDER_SELECTED",
                "uiProposal": [
                    {
                        "type": "cancellationOrderSelection",
                        "props": {},
                        "dataKey": "get_cancellation_eligible_orders_tool",
                    }
                ],
            }
            return state

    cancellable_items = [
        item for item in selected_order.get("items", []) if item.get("cancellableQuantity", 0) > 0
    ]

    if not cancellable_items:
        state["_decision"] = {
            "action": "FINISH",
            "message": f"There's nothing left to cancel on order {selected_order['orderNumber']}.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    selected_items = state.get("_selectedLineItems")

    if selected_items is not None:
        # An explicit ITEM_SELECTED resume already narrowed this down —
        # use it as-is (it was already validated against
        # _compute_offered_candidates before being admitted; the sensitive
        # tool's own dry-run re-validates authoritatively either way).
        line_selections = selected_items
    elif len(cancellable_items) == 1:
        # Only one real choice — nothing to ask, mirrors the single-order
        # auto-select shortcut above.
        line_selections = [
            {"orderLineId": item["orderLineId"], "quantity": item["cancellableQuantity"]}
            for item in cancellable_items
        ]
    else:
        state["_decision"] = {
            "action": "ASK_CUSTOMER",
            "message": f"Which items on order {selected_order['orderNumber']} would you like to cancel?",
            "toolName": None,
            "toolArgs": {},
            "interactionType": "ITEM_SELECTED",
            "uiProposal": [
                {
                    "type": "cancellationItemSelection",
                    "props": {},
                    "dataKey": "get_cancellation_eligible_orders_tool",
                }
            ],
        }
        return state

    state["_decision"] = {
        "action": "CALL_TOOL",
        "toolName": "submit_order_cancellation_tool",
        "toolArgs": {
            "order_number": selected_order["orderNumber"],
            "line_selections": line_selections,
            "reason": "Customer requested cancellation",
        },
        "message": f"I'll cancel that on order {selected_order['orderNumber']}. Let's confirm.",
        "uiProposal": [],
    }
    return state


def _deterministic_wrong_delivery(state: AgentStateV2) -> AgentStateV2:
    tool_results = state.get("toolResults", {})

    if state.get("_confirmationDeclined"):
        state["_confirmationDeclined"] = False
        state["_decision"] = {
            "action": "FINISH",
            "message": "No problem — I won't submit that claim. Let me know if there's anything else I can help with.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    order_number = _resolve_order_number(state)

    dashboard = tool_results.get("get_order_status_tool")

    if not dashboard:
        if not order_number:
            # No "list my orders" tool for this capability (plan section
            # 9-10) — ask for the order number directly rather than
            # offering a structured list that doesn't exist here.
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                "message": "Which order is this about? You can give me the order number, like U-1002.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }
            return state

        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_order_status_tool",
            "toolArgs": {"order_number": order_number},
            "message": "",
            "uiProposal": [],
        }
        return state

    # Order status already fetched — propose the claim. The sensitive
    # tool's own dry-run (request_confirmation_node) is the authoritative
    # eligibility check (e.g. rejecting an order that was never delivered);
    # this deterministic fallback doesn't duplicate that logic here.
    description = state.get("userMessage", "") or "Customer reported a wrong/missing delivery."
    state["_decision"] = {
        "action": "CALL_TOOL",
        "toolName": "submit_wrong_delivery_claim_tool",
        "toolArgs": {"order_number": order_number or dashboard.get("order", {}).get("orderNumber"), "description": description},
        "message": f"I'll file a wrong-delivery claim for order {order_number}. Let's confirm.",
        "uiProposal": [],
    }
    return state


def _deterministic_returns(state: AgentStateV2) -> AgentStateV2:
    tool_results = state.get("toolResults", {})

    if state.get("_confirmationDeclined"):
        state["_confirmationDeclined"] = False
        state["_decision"] = {
            "action": "FINISH",
            "message": "No problem — I won't return that. Anything else I can help with?",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    eligibility = tool_results.get("get_return_eligible_items_tool")

    if eligibility:
        # Already checked one specific order's eligibility this turn —
        # get_return_eligible_items_tool is the sole authority here, never
        # re-derived or assumed.
        if not eligibility.get("eligible"):
            state["_decision"] = {
                "action": "FINISH",
                "message": eligibility.get("reason")
                or f"Order {eligibility.get('orderNumber')} isn't eligible for a return.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }
            return state

        returnable_items = [
            item for item in (eligibility.get("items") or []) if item.get("returnableQuantity", 0) > 0
        ]

        if not returnable_items:
            state["_decision"] = {
                "action": "FINISH",
                "message": f"There's nothing left to return on order {eligibility.get('orderNumber')}.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }
            return state

        selected_items = state.get("_selectedLineItems")

        if selected_items is None:
            if len(returnable_items) == 1:
                selected_items = [
                    {"orderLineId": item["orderLineId"], "quantity": item["returnableQuantity"]}
                    for item in returnable_items
                ]
            else:
                state["_decision"] = {
                    "action": "ASK_CUSTOMER",
                    "message": f"Which items on order {eligibility['orderNumber']} would you like to return?",
                    "toolName": None,
                    "toolArgs": {},
                    "interactionType": "ITEM_SELECTED",
                    "uiProposal": [
                        {
                            "type": "returnItemSelection",
                            "props": {},
                            "dataKey": "get_return_eligible_items_tool",
                        }
                    ],
                }
                return state

        reason = state.get("_selectedReason")

        if reason is None:
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                # Names the order explicitly (2026-08 free-text-context fix)
                # — this order may have been carried over silently via
                # lastKnownOrderNumber rather than asked for, and this stage
                # is otherwise the customer's first/only cue which order is
                # actually being discussed. Matches the item-selection
                # stage's existing pattern above.
                "message": f"Why are you returning your order {eligibility['orderNumber']}?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "REASON_SELECTED",
                "uiProposal": [
                    {"type": "returnReasonPrompt", "props": {}, "dataKey": None}
                ],
            }
            return state

        available_methods = eligibility.get("returnMethods") or []
        method = state.get("_selectedReturnMethod")

        if method is None and len(available_methods) > 1:
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                "message": f"How would you like to return order {eligibility['orderNumber']} — by mail or in-store?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "RETURN_METHOD_SELECTED",
                "uiProposal": [
                    {"type": "returnMethodPrompt", "props": {}, "dataKey": "get_return_eligible_items_tool"}
                ],
            }
            return state

        tool_args = {
            "order_number": eligibility["orderNumber"],
            "line_selections": selected_items,
            "reason": reason,
        }
        if method is not None:
            tool_args["method"] = method

        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "create_return_tool",
            "toolArgs": tool_args,
            "message": f"I'll submit that return for order {eligibility['orderNumber']}. Let's confirm.",
            "uiProposal": [],
        }
        return state

    order_number = _resolve_order_number(state)

    if order_number:
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_return_eligible_items_tool",
            "toolArgs": {"order_number": order_number},
            "message": "",
            "uiProposal": [],
        }
        return state

    eligible_orders_result = tool_results.get("get_return_eligible_orders_tool")

    if not eligible_orders_result:
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_return_eligible_orders_tool",
            "toolArgs": {},
            "message": "",
            "uiProposal": [],
        }
        return state

    orders = (eligible_orders_result or {}).get("orders") or []

    if not orders:
        state["_decision"] = {
            "action": "FINISH",
            "message": "I don't see any orders that are currently eligible for a return.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
        return state

    if len(orders) == 1:
        state["_decision"] = {
            "action": "CALL_TOOL",
            "toolName": "get_return_eligible_items_tool",
            "toolArgs": {"order_number": orders[0]["orderNumber"]},
            "message": "",
            "uiProposal": [],
        }
        return state

    state["_decision"] = {
        "action": "ASK_CUSTOMER",
        "message": "Which order would you like to return an item from?",
        "toolName": None,
        "toolArgs": {},
        "interactionType": "ORDER_SELECTED",
        "uiProposal": [
            {"type": "orderSelection", "props": {}, "dataKey": "get_return_eligible_orders_tool"}
        ],
    }
    return state


def _apply_structured_selection(state: AgentStateV2, selection: Dict[str, Any]) -> AgentStateV2:
    """
    Merges a validated structured selection into the SAME scratch state
    each capability's deterministic function already knows how to consume
    — never into userMessage/free text. This is the mechanism that
    prevents an unambiguous UI selection from ever being reinterpreted as
    customer prose (2026-08 structured-interaction fix — see
    ask_customer_node's resume handling for where selections are
    validated before reaching here).
    """

    interaction_type = selection.get("type")
    payload = selection.get("payload") or {}

    if interaction_type == "ORDER_SELECTED":
        state["_classification"] = {
            **(state.get("_classification") or {}),
            "orderNumber": payload.get("orderNumber"),
        }
    elif interaction_type == "ITEM_SELECTED":
        state["_selectedLineItems"] = payload.get("selections") or []
    elif interaction_type == "REASON_SELECTED":
        state["_selectedReason"] = payload.get("reason")
    elif interaction_type == "RETURN_METHOD_SELECTED":
        state["_selectedReturnMethod"] = payload.get("method")

    return state


# ---------------------------------------------------------------------------
# Bounded free-text slot-filling (2026-08 free-text-context fix). Scoped
# deliberately narrow: REASON_SELECTED/RETURN_METHOD_SELECTED only — both
# are "pick one of a small fixed set of strings", the case where a customer
# is likeliest to answer in their own words ("it's too small", "by mail")
# rather than clicking. ORDER_SELECTED already has a working deterministic
# path for free text (_resolve_order_number's regex extraction handles "for
# U-1002"); ITEM_SELECTED needs quantities per line, which is a materially
# harder and riskier extraction to leave to an LLM — out of scope for this
# pass, it still falls through to the existing corrective re-ask.
#
# This NEVER decides ASK_CUSTOMER vs FINISH and NEVER calls a tool — its
# only possible output is "one of these exact candidate strings, or
# nothing." A result outside the offered candidates is never applied (the
# containment check below is this call's own version of the same
# never-trust-structured-input-blindly principle _validate_structured_payload
# applies to a real button click — plan section 18a correction 3).
# ---------------------------------------------------------------------------


class _SlotFillAttempt(BaseModel):
    matchedValue: Optional[str] = Field(
        default=None,
        description=(
            "Verbatim one of the offered candidate strings that the "
            "customer's reply clearly matches (including paraphrases/"
            "synonyms), or omit entirely if it doesn't confidently match "
            "any of them — e.g. it's a question, an unrelated comment, or "
            "too ambiguous."
        ),
    )


# stage -> (interactionType, offered-candidates key, AgentStateV2 field to
# fill, selectionSummary key)
_SLOT_FILL_ELIGIBLE_STAGES: Dict[str, "tuple[str, str, str, str]"] = {
    "WAITING_FOR_REASON": ("REASON_SELECTED", "reasons", "_selectedReason", "reason"),
    "WAITING_FOR_METHOD": ("RETURN_METHOD_SELECTED", "methods", "_selectedReturnMethod", "method"),
}


def _attempt_free_text_slot_fill(candidates: List[str], message: str) -> Optional[str]:
    """
    Returns the matched candidate string, or None (falls through to the
    existing deterministic re-ask) if there's no API key, the call fails,
    or the model isn't confident of a match. Failure is always safe here —
    the caller's fallback is exactly what would have happened before this
    fix existed.
    """

    if not os.getenv("OPENAI_API_KEY") or not candidates or not message:
        return None

    try:
        llm = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            timeout=loop_safety.LLM_TIMEOUT_SECONDS,
        ).with_structured_output(_SlotFillAttempt)

        result = llm.invoke(
            [
                (
                    "system",
                    "The customer was just asked a question with a small fixed set "
                    "of valid answers. Decide whether their reply clearly matches "
                    "ONE of the offered candidates below, including paraphrases "
                    "and synonyms. Never guess — leave matchedValue unset unless "
                    "you're confident.",
                ),
                ("human", f"Offered candidates: {candidates}\nCustomer's reply: {message}"),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - falls through to the deterministic re-ask, never crashes the turn
        print(f"[v2.graph] slot-fill attempt failed, falling back to re-ask: {exc}")
        return None

    if result.matchedValue in candidates:
        return result.matchedValue
    return None


def _deterministic_agent_reason(state: AgentStateV2, capability) -> AgentStateV2:
    """
    No-API-key / LLM-failure resilience path, mirroring V1's own zero-key
    fallback ethos so V2 is demoable and testable without a real API key.
    Dispatches by capability name — each capability's deterministic logic
    lives in its own small function rather than one growing conditional.
    """

    if capability.name == "CANCELLATION":
        return _deterministic_cancellation(state)
    if capability.name == "WRONG_DELIVERY":
        return _deterministic_wrong_delivery(state)
    if capability.name == "RETURNS":
        return _deterministic_returns(state)

    return _deterministic_order_status(state)


def agent_reason_node(state: AgentStateV2) -> AgentStateV2:
    capability = get_capability(state["activeCapability"])
    stopwatch = Stopwatch()

    structured_selection = state.get("_structuredSelection")

    if structured_selection:
        # A validated structured UI selection (order/item/reason/method) is
        # a mechanical fact, not something requiring interpretation —
        # apply it and let the capability's own deterministic progression
        # decide the next step, ALWAYS, even with an API key configured.
        # This is what "never reinterpret an unambiguous structured
        # selection" means structurally: the LLM is never invoked for this
        # one step (2026-08 structured-interaction fix).
        state["_structuredSelection"] = None
        state = _apply_structured_selection(state, structured_selection)
        state = _deterministic_agent_reason(state, capability)
        decision = state.get("_decision", {})
        _record_conversation_turn(state, "assistant", decision.get("message") or "")
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model="deterministic-structured-advance",
            latencyMs=stopwatch.elapsed_ms(),
            interactionType=structured_selection.get("type"),
            interactionSource="A2UI",
            selectionSummary=structured_selection.get("payload"),
            validatedAgainstCandidates=True,
        )
        return state

    workflow_stage = _compute_workflow_stage(state)

    if workflow_stage in _MANDATORY_ASK_STAGES:
        # Deterministic gate (2026-08 workflow-stage fix): once the
        # workflow has landed on a REQUIRED, enumerable structured choice
        # (which order/items/reason/method), asking for it is never left
        # to the LLM's own ask-vs-finish judgment — this is exactly the
        # bug that let a candidate list get enumerated in FINISH prose
        # with a mandatory a2ui screen attached to an already-FINAL turn
        # (no pending interrupt underneath it), or let the LLM burn loop
        # iterations re-calling a tool it already has fresh results for
        # instead of asking. The capability's own deterministic function
        # already encodes exactly this ask (message + a2ui type), so it's
        # reused here rather than duplicated — this ALSO satisfies "don't
        # duplicate structured A2UI details in prose" for free, since
        # those messages are already short/non-enumerating by design.
        #
        # Before falling to that pure re-ask, give free text one bounded
        # chance to actually answer the question (2026-08 free-text-context
        # fix) — REASON_SELECTED/RETURN_METHOD_SELECTED stages only (see
        # _attempt_free_text_slot_fill's docstring for why). Without this,
        # a customer typing "it's too small" instead of clicking a button
        # got the exact same reason-prompt repeated verbatim, forever, since
        # the deterministic functions only ever check their own scratch
        # fields (_selectedReason etc.), never userMessage.
        slot_fill_spec = _SLOT_FILL_ELIGIBLE_STAGES.get(workflow_stage)
        if slot_fill_spec and state.get("userMessage"):
            interaction_type, candidates_key, state_field, summary_key = slot_fill_spec
            candidates = _compute_offered_candidates(state).get(candidates_key) or []
            matched = _attempt_free_text_slot_fill(candidates, state["userMessage"])

            if matched:
                state[state_field] = matched
                state["userMessage"] = ""  # consumed — never reinterpreted downstream
                state = _deterministic_agent_reason(state, capability)
                decision = state.get("_decision", {})
                _record_conversation_turn(state, "assistant", decision.get("message") or "")
                _emit(
                    state,
                    agentAction=decision.get("action"),
                    requestedTool=decision.get("toolName"),
                    model="bounded-slot-fill",
                    latencyMs=stopwatch.elapsed_ms(),
                    interactionType=interaction_type,
                    interactionSource="FREE_TEXT",
                    selectionSummary={summary_key: matched},
                    validatedAgainstCandidates=True,
                )
                return state

        state = _deterministic_agent_reason(state, capability)
        decision = state.get("_decision", {})
        _record_conversation_turn(state, "assistant", decision.get("message") or "")
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model="deterministic-workflow-gate",
            latencyMs=stopwatch.elapsed_ms(),
        )
        return state

    if not os.getenv("OPENAI_API_KEY"):
        state = _deterministic_agent_reason(state, capability)
        decision = state.get("_decision", {})
        _record_conversation_turn(state, "assistant", decision.get("message") or "")
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model="deterministic-fallback",
            latencyMs=stopwatch.elapsed_ms(),
        )
        return state

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        max_tokens=300,
        timeout=loop_safety.LLM_TIMEOUT_SECONDS,
    ).bind_tools(list(capability.tools) + [ask_customer, finish])

    try:
        ai_message = llm.invoke(_build_messages(state, capability))
    except Exception as exc:  # noqa: BLE001 - mirrors V1's broad catch-and-fallback
        print(f"[v2.graph] agent_reason failed, using deterministic fallback: {exc}")
        state = _deterministic_agent_reason(state, capability)
        decision = state.get("_decision", {})
        _record_conversation_turn(state, "assistant", decision.get("message") or "")
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model=model_name,
            latencyMs=stopwatch.elapsed_ms(),
            retryOrError=str(exc),
        )
        return state

    usage = getattr(ai_message, "usage_metadata", None) or {}

    if not ai_message.tool_calls:
        state["_decision"] = {
            "action": "FINISH",
            "message": ai_message.content or "I'm not sure how to help with that yet.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
    else:
        call = ai_message.tool_calls[0]
        name = call.get("name")
        args = call.get("args") or {}

        if name == "finish":
            state["_decision"] = {
                "action": "FINISH",
                "message": args.get("message", ""),
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }
        elif name == "ask_customer":
            ask_type = args.get("askType") or "FREEFORM"
            a2ui_type = _ASK_TYPE_TO_A2UI.get((capability.name, ask_type))
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                "message": args.get("question", ""),
                "toolName": None,
                "toolArgs": {},
                "interactionType": ask_type,
                "uiProposal": (
                    [{"type": a2ui_type, "props": {}, "dataKey": None}] if a2ui_type else []
                ),
            }
        else:
            state["_decision"] = {
                "action": "CALL_TOOL",
                "toolName": name,
                "toolArgs": args,
                "message": "",
                "uiProposal": [],
            }

    decision = state["_decision"]
    _record_conversation_turn(state, "assistant", decision.get("message") or "")
    _emit(
        state,
        agentAction=decision.get("action"),
        requestedTool=decision.get("toolName"),
        model=model_name,
        promptTokens=usage.get("input_tokens"),
        completionTokens=usage.get("output_tokens"),
        latencyMs=stopwatch.elapsed_ms(),
    )

    return state


def execute_tool_node(state: AgentStateV2) -> AgentStateV2:
    decision = state.get("_decision", {})
    tool_name = decision.get("toolName")
    tool_args = decision.get("toolArgs") or {}
    # Computed once, before the tool runs, so the SAME stage value scopes
    # both the repeated-call check and the signature it records (2026-08
    # workflow-stage fix) — see loop_safety.is_repeated_call's docstring.
    workflow_stage = _compute_workflow_stage(state)

    capability = get_capability(state["activeCapability"])
    tool_by_name = {t.name: t for t in capability.tools}

    call_id = str(uuid.uuid4())
    started_at = _now()
    stopwatch = Stopwatch()

    record: Dict[str, Any] = {
        "callId": call_id,
        "toolName": tool_name,
        "argsSummary": tool_args,
        "resultSummary": None,
        "isSensitive": tool_name in capability.sensitive_tool_names,
        "startedAt": started_at,
        "finishedAt": None,
        "error": None,
    }

    if tool_name not in tool_by_name:
        # Defense in depth beyond .bind_tools() scoping (plan section 30) —
        # an out-of-scope tool name is rejected, never executed.
        error = f"Tool '{tool_name}' is not available for capability {capability.name}."
        record["error"] = error
        record["finishedAt"] = _now()
        state.setdefault("toolLog", []).append(record)
        state.setdefault("toolResults", {})[tool_name or "unknown"] = {"error": error}
        state["loopIteration"] = state.get("loopIteration", 0) + 1
        _emit(
            state,
            agentAction="CALL_TOOL",
            requestedTool=tool_name,
            toolInputSummary=tool_args,
            retryOrError=error,
            latencyMs=stopwatch.elapsed_ms(),
        )
        return state

    if tool_name in capability.sensitive_tool_names:
        # Defense in depth: route_after_agent_reason should always send a
        # sensitive tool call to request_confirmation instead of here — if
        # this is ever reached anyway (e.g. a future routing bug), refuse
        # rather than silently executing a transactional action outside
        # the confirmation gate.
        error = f"Tool '{tool_name}' is sensitive and must go through confirmation — it cannot be called directly."
        record["error"] = error
        record["finishedAt"] = _now()
        state.setdefault("toolLog", []).append(record)
        state.setdefault("toolResults", {})[tool_name] = {"error": error}
        state["loopIteration"] = state.get("loopIteration", 0) + 1
        _emit(
            state,
            agentAction="CALL_TOOL",
            requestedTool=tool_name,
            toolInputSummary=tool_args,
            retryOrError=error,
            latencyMs=stopwatch.elapsed_ms(),
        )
        return state

    if loop_safety.is_repeated_call(state, tool_name, tool_args, workflow_stage):
        # Short-circuit before actually invoking anything (plan section 30)
        # — this is a redirect/nudge, not itself an escalation.
        note = (
            "This exact request was already made twice this turn — use the "
            "existing result or ask the customer instead of repeating it."
        )
        record["resultSummary"] = {"note": note}
        record["finishedAt"] = _now()
        state.setdefault("toolLog", []).append(record)
        state.setdefault("toolResults", {})[tool_name] = {"note": note}
        state["loopIteration"] = state.get("loopIteration", 0) + 1
        _emit(
            state,
            agentAction="CALL_TOOL",
            requestedTool=tool_name,
            toolInputSummary=tool_args,
            toolResultSummary={"note": note},
            retryOrError="repeated_call_short_circuited",
            latencyMs=stopwatch.elapsed_ms(),
        )
        return state

    try:
        result = loop_safety.run_with_timeout(
            lambda: tool_by_name[tool_name].invoke(tool_args),
            loop_safety.TOOL_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - tool failures (incl. timeouts) are surfaced, not swallowed
        result = {"error": str(exc)}
        record["error"] = str(exc)

    record["finishedAt"] = _now()
    record["resultSummary"] = _summarize(result)

    state.setdefault("toolLog", []).append(record)
    state.setdefault("toolResults", {})[tool_name] = result
    state["loopIteration"] = state.get("loopIteration", 0) + 1
    loop_safety.record_call_signature(state, tool_name, tool_args, workflow_stage)

    if not record["error"] and tool_args.get("order_number"):
        # Survives capability switches (see AgentStateV2.lastKnownOrderNumber)
        # so a pivot like ORDER_STATUS -> WRONG_DELIVERY can carry the order
        # forward instead of re-asking, even though toolResults itself gets
        # cleared on switch.
        state["lastKnownOrderNumber"] = tool_args["order_number"]

    if record["error"]:
        failures = loop_safety.consecutive_failure_count(state, tool_name)
        if failures > loop_safety.MAX_RETRIES_PER_TOOL:
            loop_safety.escalate(state, f"tool_retry_limit_exceeded:{tool_name}")

    _emit(
        state,
        agentAction="CALL_TOOL",
        requestedTool=tool_name,
        toolInputSummary=tool_args,
        toolResultSummary=record["resultSummary"],
        retryOrError=record["error"],
        latencyMs=stopwatch.elapsed_ms(),
    )

    return state


def _validate_structured_payload(
    interaction_type: str, payload: Dict[str, Any], candidates: Dict[str, Any]
) -> "tuple[bool, Optional[str]]":
    """
    Deterministic candidate-membership validation, one branch per
    interaction type — never trusts a structured selection outright just
    because its shape is unambiguous (plan section 18a, correction 3;
    2026-08 structured-interaction fix generalizes this beyond order
    numbers). Returns (ok, corrective_message_or_None).
    """

    if interaction_type == "ORDER_SELECTED":
        order_number = payload.get("orderNumber")
        if not order_number or order_number not in (candidates.get("orderNumbers") or []):
            return False, "That doesn't match one of the orders I listed — could you pick one of these?"
        return True, None

    if interaction_type == "ITEM_SELECTED":
        selections = payload.get("selections") or []
        items = candidates.get("items") or {}

        if not selections:
            return False, "Please select at least one item."

        for selection in selections:
            line_id = selection.get("orderLineId")
            quantity = selection.get("quantity")
            candidate = items.get(line_id)

            if not candidate:
                return False, "That doesn't match one of the items I listed — could you pick from these?"
            if not isinstance(quantity, int) or quantity <= 0 or quantity > candidate["maxQuantity"]:
                return False, "One of those quantities isn't available — could you double-check and try again?"

        return True, None

    if interaction_type == "REASON_SELECTED":
        reason = payload.get("reason")
        if not reason or reason not in (candidates.get("reasons") or []):
            return False, "Please pick one of the listed reasons."
        return True, None

    if interaction_type == "RETURN_METHOD_SELECTED":
        method = payload.get("method")
        if not method or method not in (candidates.get("methods") or []):
            return False, "Please pick one of the listed return methods."
        return True, None

    return False, "That selection isn't valid right now."


def ask_customer_node(state: AgentStateV2) -> AgentStateV2:
    """
    Real interrupt()-based pause. Per LangGraph's interrupt() semantics, on
    resume the graph re-executes this node FROM THE TOP — everything above
    the interrupt() call below re-runs (idempotently, recomputed from
    state) before the resumed value is available. Nothing this node
    computes before interrupt() is committed to the graph's persisted state
    (the node never "returns" on the interrupting pass) — the question/UI
    shown to the customer is surfaced via the value passed to interrupt(),
    which the router reads from the invoke() result's "__interrupt__" key.
    """

    decision = state.get("_decision", {})
    active_capability = state["activeCapability"]

    if active_capability in CAPABILITIES:
        capability = get_capability(active_capability)
        components, origin = validate_agent_a2ui(
            decision.get("uiProposal") or [], capability, state.get("toolResults", {})
        )
    else:
        # CLARIFY has no registered Capability/tool catalog to validate
        # against — clarify_node never sets a uiProposal, so this is
        # always the deterministic welcome fallback in practice.
        components, origin = [{"type": "welcome", "props": {}, "dataKey": None}], "DETERMINISTIC_FALLBACK"

    question = decision.get("message") or "Could you tell me more?"
    expected_interaction_type = decision.get("interactionType", "FREEFORM")
    candidates = _compute_offered_candidates(state)

    interrupt_ui_state = {
        "uiMode": components[0]["type"] if components else "welcome",
        "assistantMessage": question,
        "canvasData": _build_canvas_data(state),
        "a2ui": components,
    }

    resumed = interrupt(
        {
            "interruptType": "ASK_CUSTOMER",
            "expectedInteractionType": expected_interaction_type,
            "message": question,
            "uiState": interrupt_ui_state,
            "a2uiOrigin": origin,
            "offeredCandidates": candidates,
        }
    )

    # --- everything below only runs after Command(resume=...) ---

    if isinstance(resumed, dict) and resumed.get("__abandon__"):
        # Detect + forward ONLY (correction 2) — enforce_capability_switch
        # is the single owner of archiving/clearing, never this node.
        state["_pendingPivot"] = {
            "newMessage": resumed.get("newMessage", ""),
            "classification": resumed.get("classification"),
        }
        state["_reAsk"] = False
        _emit(state, agentAction="ASK_CUSTOMER", interruptType="ASK_CUSTOMER", retryOrError="abandoned_for_pivot")
        return state

    resumed_type = resumed.get("type") if isinstance(resumed, dict) else None

    if resumed_type in ("ORDER_SELECTED", "ITEM_SELECTED", "REASON_SELECTED", "RETURN_METHOD_SELECTED"):
        # A structured, code-generated UI selection — unambiguous, but not
        # trusted outright (correction 3): every check below is
        # deterministic, none of it goes through the classifier or the
        # agent's own reasoning (2026-08 structured-interaction fix).
        resumed_capability = resumed.get("capability")
        payload = resumed.get("payload") or {}

        if resumed_type != expected_interaction_type or resumed_capability != state["activeCapability"]:
            # A stale or mismatched selection (e.g. from a screen that's no
            # longer current) — reject before it ever reaches candidate
            # validation.
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                "message": question,
                "toolName": None,
                "toolArgs": {},
                "interactionType": expected_interaction_type,
                "uiProposal": decision.get("uiProposal") or [],
            }
            state["_reAsk"] = True
            _emit(
                state,
                agentAction="RESUME",
                interruptType="ASK_CUSTOMER",
                interactionType=resumed_type,
                interactionSource="A2UI",
                validatedAgainstCandidates=False,
                retryOrError="interaction_type_or_capability_mismatch",
            )
            return state

        ok, corrective_message = _validate_structured_payload(resumed_type, payload, candidates)

        if not ok:
            state["_decision"] = {
                "action": "ASK_CUSTOMER",
                "message": corrective_message,
                "toolName": None,
                "toolArgs": {},
                "interactionType": expected_interaction_type,
                "uiProposal": decision.get("uiProposal") or [],
            }
            state["_reAsk"] = True
            _emit(
                state,
                agentAction="RESUME",
                interruptType="ASK_CUSTOMER",
                interactionType=resumed_type,
                interactionSource="A2UI",
                validatedAgainstCandidates=False,
                retryOrError="rejected_out_of_set_selection",
            )
            return state

        # Validated — handed off as structured intent, never as
        # synthesized natural-language prose. agent_reason_node consumes
        # this deterministically, without any LLM call, before anything
        # else runs this turn.
        state["_structuredSelection"] = {"type": resumed_type, "payload": payload}
        state["_reAsk"] = False
        selection_summary = (
            {"orderNumber": payload.get("orderNumber")}
            if resumed_type == "ORDER_SELECTED"
            else payload
        )
        _emit(
            state,
            agentAction="RESUME",
            interruptType="ASK_CUSTOMER",
            interactionType=resumed_type,
            interactionSource="A2UI",
            selectionSummary=selection_summary,
            validatedAgainstCandidates=True,
        )
        return state

    # Free text, already classified as a continuation by the router and
    # forwarded as the literal answer (plan section 18a, branch 3).
    customer_reply = resumed.get("customerReply") if isinstance(resumed, dict) else resumed
    state["userMessage"] = customer_reply or ""
    state["_reAsk"] = False
    _record_conversation_turn(state, "user", customer_reply or "")
    _emit(
        state,
        agentAction="ASK_CUSTOMER",
        interruptType="ASK_CUSTOMER",
        interactionSource="FREE_TEXT",
    )
    return state


def _validate_sensitive_proposal(
    state: AgentStateV2, tool_name: Optional[str], tool_args: Dict[str, Any]
):
    """
    Validates a proposed sensitive action WITHOUT ever calling the
    mutation-shaped tool itself (2026-08 premature-execution fix) —
    submit_order_cancellation/create_return/submit_wrong_delivery_claim
    only ever run once, from execute_confirmed_action_node, after a valid
    Confirm. Each branch validates the proposal against data THIS turn
    already fetched (a read-only tool result already sitting in
    toolResults), never re-derives eligibility rules from scratch — for
    CANCELLATION specifically, this is what lets request_confirmation_node
    validate without ever touching agent/tools.py's
    submit_order_cancellation (V1, protected — this project's baseline
    stays byte-for-byte unchanged).

    Returns (ok, preview_dict_or_None, error_message_or_None). The preview
    dict, when present, deliberately has no transaction id and no
    "status" field — nothing that could ever look like a completed
    submission, because nothing here ever calls the function that mints
    one.
    """

    tool_results = state.get("toolResults", {})

    try:
        if tool_name == "submit_order_cancellation_tool":
            eligible = tool_results.get("get_cancellation_eligible_orders_tool")
            preview = validate_cancellation_proposal(
                tool_args.get("order_number"),
                tool_args.get("line_selections") or [],
                tool_args.get("reason", ""),
                eligible,
            )
            return True, preview, None

        if tool_name == "create_return_tool":
            preview = build_return_preview(
                tool_args.get("order_number"),
                tool_args.get("line_selections") or [],
                tool_args.get("reason", ""),
                tool_args.get("method"),
            )
            return True, preview, None

        if tool_name == "submit_wrong_delivery_claim_tool":
            preview = build_wrong_delivery_claim_preview(
                tool_args.get("order_number"),
                tool_args.get("description", ""),
            )
            return True, preview, None
    except HTTPException as exc:
        return False, None, str(exc.detail)

    return False, None, f"Unknown sensitive action: {tool_name}"


def request_confirmation_node(state: AgentStateV2) -> AgentStateV2:
    """
    Real interrupt()-based pause for a sensitive action — reached only via
    the routing edge after agent_reason (never called for a non-sensitive
    tool). Validates the proposal via _validate_sensitive_proposal — which
    NEVER calls the underlying mutation-shaped tool (2026-08 premature-
    execution fix) — so nothing before the interrupt() call below can ever
    generate a transaction id or claim a submission succeeded; only
    execute_confirmed_action_node, after a valid Confirm, does that.

    Like ask_customer_node, this re-executes from the top on every resume,
    so pendingAction's actionId is derived deterministically (see
    confirmation.deterministic_action_id) rather than minted randomly —
    confirmed empirically that state written before interrupt() does not
    persist across a resume, so nothing here can rely on "remembering" a
    prior pass's random id. Re-running pure validation on every resume is
    harmless by construction: it's deterministic and mutates nothing, so
    it always produces the identical preview for the identical proposal.
    """

    decision = state.get("_decision", {})
    tool_name = decision.get("toolName")
    tool_args = decision.get("toolArgs") or {}
    action_type = _SENSITIVE_ACTION_TYPES.get(tool_name, (tool_name or "UNKNOWN").upper())
    stopwatch = Stopwatch()

    ok, preview_result, validation_error = _validate_sensitive_proposal(state, tool_name, tool_args)

    if not ok:
        # The agent proposed an invalid sensitive action (e.g. a quantity
        # beyond what's cancellable) — surface this as an ordinary
        # validation failure and hand back to agent_reason. A confirmation
        # screen is never shown for something that can't actually be
        # executed, and — critically — nothing was ever attempted against
        # the real mutating tool to find this out.
        state.setdefault("toolLog", []).append(
            {
                "callId": str(uuid.uuid4()),
                "toolName": tool_name,
                "argsSummary": tool_args,
                "resultSummary": None,
                "isSensitive": True,
                "startedAt": _now(),
                "finishedAt": _now(),
                "error": validation_error,
            }
        )
        state.setdefault("toolResults", {})[tool_name] = {"error": validation_error}
        state["loopIteration"] = state.get("loopIteration", 0) + 1
        state["_confirmationDryRunFailed"] = True
        state["pendingAction"] = None

        # Same retry-limit guard execute_tool_node applies (plan section
        # 30) — without it, a persistently-invalid sensitive-tool proposal
        # (e.g. an order that's structurally never going to become
        # eligible) would loop all the way to the iteration cap instead of
        # escalating promptly. Checked here too since this validation path
        # never actually reaches execute_tool_node.
        failures = loop_safety.consecutive_failure_count(state, tool_name)
        if failures > loop_safety.MAX_RETRIES_PER_TOOL:
            loop_safety.escalate(state, f"tool_retry_limit_exceeded:{tool_name}")

        _emit(
            state,
            agentAction="PROPOSE_SENSITIVE_ACTION",
            requestedTool=tool_name,
            retryOrError=validation_error,
            latencyMs=stopwatch.elapsed_ms(),
        )
        return state

    state["_confirmationDryRunFailed"] = False

    action_id = confirmation.deterministic_action_id(
        state.get("threadId") or "local",
        state.get("loopIteration", 0),
        tool_name,
        tool_args,
    )
    pending = confirmation.create_pending_action(
        action_id, action_type, state["activeCapability"], tool_args, eligibility_checked=True
    )
    state["pendingAction"] = pending

    mandatory_ui = build_mandatory_ui(
        action_type, "PENDING", {"preview": preview_result, "pending": pending}
    )
    message = decision.get("message") or "Please review and confirm."

    interrupt_ui_state = {
        "uiMode": mandatory_ui[0]["type"] if mandatory_ui else "welcome",
        "assistantMessage": message,
        "canvasData": {"preview": preview_result},
        "a2ui": mandatory_ui,
    }

    _emit(
        state,
        agentAction="PROPOSE_SENSITIVE_ACTION",
        requestedTool=tool_name,
        toolResultSummary=preview_result,
        confirmationActionId=pending["actionId"],
        latencyMs=stopwatch.elapsed_ms(),
    )

    resumed = interrupt(
        {
            "interruptType": "CONFIRM_ACTION",
            "actionId": pending["actionId"],
            "actionType": action_type,
            "message": message,
            "uiState": interrupt_ui_state,
        }
    )

    # --- everything below only runs after Command(resume=...) ---

    if isinstance(resumed, dict) and resumed.get("__abandon__"):
        # Detect + forward ONLY (correction 2) — enforce_capability_switch
        # is the single owner of archiving/clearing, never this node.
        state["_pendingPivot"] = {
            "newMessage": resumed.get("newMessage", ""),
            "classification": resumed.get("classification"),
        }
        state["_confirmationReminder"] = False
        _emit(state, agentAction="CONFIRM_ACTION", interruptType="CONFIRM_ACTION", retryOrError="abandoned_for_pivot")
        return state

    if isinstance(resumed, dict) and resumed.get("__confirmationReminder__"):
        # Free text arrived, but this is a CONFIRM_ACTION interrupt — never
        # treated as authorization (correction 1). pendingAction is
        # untouched; the conditional edge re-interrupts with it unchanged.
        state["_confirmationReminder"] = True
        _emit(
            state,
            agentAction="CONFIRM_ACTION",
            interruptType="CONFIRM_ACTION",
            retryOrError="confirmation_reminder_not_authorization",
        )
        return state

    state["_confirmationReminder"] = False

    if isinstance(resumed, dict) and "confirmation" in resumed:
        # The only shape that ever proceeds to validate_confirmation —
        # produced solely by a real Confirm/Decline button click. Full
        # (re-)validation happens in execute_confirmed_action_node right
        # before executing anything — nothing here is a decision, only a
        # forward.
        state["_confirmationReply"] = resumed["confirmation"]
        _emit(
            state,
            agentAction="CONFIRM_ACTION",
            interruptType="CONFIRM_ACTION",
            interactionType="CONFIRM_ACTION",
            interactionSource="A2UI",
        )
        return state

    # Unexpected resume shape — never a dangerous default: treat it as a
    # reminder (re-interrupt with the same pendingAction unchanged) rather
    # than silently proceeding as if it were authorization.
    state["_confirmationReminder"] = True
    _emit(
        state,
        agentAction="CONFIRM_ACTION",
        interruptType="CONFIRM_ACTION",
        retryOrError="unexpected_resume_shape",
    )
    return state


def execute_confirmed_action_node(state: AgentStateV2) -> AgentStateV2:
    """
    Reached only after request_confirmation resumes with a real
    {"confirmation": {...}} payload. Runs all seven validate_confirmation
    checks before anything executes; an idempotency replay returns the
    already-recorded result instead of re-executing (plan section 21);
    every other rejection reason clears the stale pendingAction and hands
    back to agent_reason rather than silently retrying.
    """

    confirmation_reply = state.get("_confirmationReply") or {}
    pending = state.get("pendingAction")
    result = confirmation.validate_confirmation(pending, confirmation_reply)
    state["_confirmationReply"] = None

    if not result.ok:
        if result.reason == "IDEMPOTENCY_REPLAY" and pending:
            cached_result = idempotency.get_recorded_result(pending["actionId"])
            mandatory_ui = build_mandatory_ui(
                pending["actionType"], "CONFIRMED", {"result": cached_result}
            )
            state["_mandatoryUi"] = mandatory_ui
            state["_decision"] = {
                "action": "FINISH",
                "message": "This was already submitted — here's the confirmation.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }
            state["_confirmationInvalid"] = None
            _emit(
                state,
                agentAction="REPLAY_SHORT_CIRCUITED",
                interactionType="CONFIRM_ACTION",
                interactionSource="A2UI",
                validatedAgainstCandidates=False,
                confirmationActionId=pending["actionId"],
                retryOrError="idempotency_replay_returned_cached_result",
                finalOutcome="FINAL",
            )
            return state

        # Any other rejection: never execute, never silently retry. Clear
        # the stale pendingAction and hand back to agent_reason.
        state["pendingAction"] = None
        state["_confirmationInvalid"] = result.reason
        _emit(
            state,
            agentAction="CONFIRM_ACTION",
            interactionType="CONFIRM_ACTION",
            interactionSource="A2UI",
            validatedAgainstCandidates=False,
            retryOrError=f"confirmation_rejected:{result.reason}",
        )
        return state

    state["_confirmationInvalid"] = None

    if not result.accepted:
        # Declined: consumed, never executed — control returns to
        # agent_reason to respond conversationally rather than through a
        # mandatory completion screen (declining isn't a transactional
        # completion state).
        pending["consumed"] = True
        state["pendingAction"] = None
        state.setdefault("toolResults", {})["_confirmationDeclined"] = True
        state["_confirmationDeclined"] = True
        _emit(
            state,
            agentAction="CONFIRM_ACTION",
            interactionType="CONFIRM_ACTION",
            interactionSource="A2UI",
            validatedAgainstCandidates=True,
            confirmationActionId=pending["actionId"],
            retryOrError="declined",
        )
        return state

    # Accepted and fully valid: execute the real sensitive tool call now,
    # using the FROZEN proposedPayload (not whatever might be in
    # decision.toolArgs) — the pending action's payload is the one thing
    # that was actually shown to and confirmed by the customer.
    tool_name = _ACTION_TYPE_TO_TOOL_NAME.get(pending["actionType"])
    capability = get_capability(pending["capability"])
    tool_by_name = {t.name: t for t in capability.tools}
    stopwatch = Stopwatch()

    try:
        exec_result = tool_by_name[tool_name].invoke(pending["proposedPayload"])
        exec_error = None
    except Exception as exc:  # noqa: BLE001 - surfaced via toolLog, not swallowed
        exec_result = {"error": str(exc)}
        exec_error = str(exc)

    state.setdefault("toolLog", []).append(
        {
            "callId": str(uuid.uuid4()),
            "toolName": tool_name,
            "argsSummary": pending["proposedPayload"],
            "resultSummary": exec_result,
            "isSensitive": True,
            "startedAt": _now(),
            "finishedAt": _now(),
            "error": exec_error,
        }
    )
    state.setdefault("toolResults", {})[tool_name] = exec_result

    pending["consumed"] = True
    pending["executed"] = True
    state["pendingAction"] = pending
    idempotency.record_executed(pending["actionId"], exec_result)

    mandatory_ui = build_mandatory_ui(pending["actionType"], "CONFIRMED", {"result": exec_result})
    state["_mandatoryUi"] = mandatory_ui
    state["_decision"] = {
        "action": "FINISH",
        "message": _confirmed_action_message(pending["actionType"], exec_result),
        "toolName": None,
        "toolArgs": {},
        "uiProposal": [],
    }

    _emit(
        state,
        agentAction="EXECUTE_SENSITIVE_ACTION",
        interactionType="CONFIRM_ACTION",
        interactionSource="A2UI",
        validatedAgainstCandidates=True,
        requestedTool=tool_name,
        toolResultSummary=exec_result,
        confirmationActionId=pending["actionId"],
        latencyMs=stopwatch.elapsed_ms(),
        finalOutcome="FINAL",
    )

    return state


def _confirmed_action_message(action_type: str, exec_result: Dict[str, Any]) -> str:
    if action_type == "SUBMIT_CANCELLATION" and isinstance(exec_result, dict) and not exec_result.get("error"):
        order_number = exec_result.get("orderNumber", "your order")
        resulting_status = exec_result.get("resultingOrderStatus", "cancelled")
        return f"Done — {order_number} has been submitted for cancellation. Status: {resulting_status}."

    if action_type == "SUBMIT_WRONG_DELIVERY_CLAIM" and isinstance(exec_result, dict) and not exec_result.get("error"):
        claim_id = exec_result.get("claimId", "your claim")
        sla_message = exec_result.get("slaMessage", "")
        return f"Done — claim {claim_id} has been submitted. {sla_message}".strip()

    if action_type == "CREATE_RETURN" and isinstance(exec_result, dict) and not exec_result.get("error"):
        order_number = exec_result.get("orderNumber", "your order")
        refund_estimate = exec_result.get("refundEstimate")
        refund_text = f" Estimated refund: ${refund_estimate:.2f}." if refund_estimate is not None else ""
        return f"Done — your return for {order_number} has been submitted.{refund_text}"

    return "Your request has been submitted."


def _suggested_replies_for_finish(
    state: AgentStateV2, active_capability: Optional[str], mandatory_ui: Optional[List[Dict[str, Any]]]
) -> Optional[List[str]]:
    """
    Contextual next-step chips attached to THIS turn (2026-08 fix) — the
    per-turn replacement for the permanent "Choose a support option" panel
    the frontend used to show for the whole conversation. Same mechanism
    V1 already populates via uiState.suggestedReplies, computed here for
    V2. Deliberately narrow: only offered after a plain informational
    answer, never after a just-completed transactional action (its own
    confirmation card already reads as "done" — a nudge there is noise,
    not help) and never on an error/escalation.
    """

    if mandatory_ui is not None or state.get("status") == "ERROR":
        return None

    if active_capability == "ORDER_STATUS" and "get_order_status_tool" in state.get("toolResults", {}):
        return ["Track a different order"]

    return None


def finish_node(state: AgentStateV2) -> AgentStateV2:
    decision = state.get("_decision", {})
    message = decision.get("message") or "Here's what I found."
    active_capability = state["activeCapability"]

    # Catch-all: agent_reason_node/execute_confirmed_action_node already
    # record their own FINISH message where they set it, but a few paths
    # (loop_safety.escalate(), called from execute_tool_node/
    # request_confirmation_node/clarify_node) set _decision directly and
    # route straight here without going through either of those. Recording
    # here too is safe — _record_conversation_turn is idempotent against an
    # identical immediately-preceding entry.
    _record_conversation_turn(state, "assistant", message)

    mandatory_ui = state.get("_mandatoryUi")

    if mandatory_ui is not None:
        # Code-owned transactional/completion UI (plan section 22) — never
        # passed through validate_agent_a2ui. The agent's uiProposal (if
        # any) is never even read on this path, by construction.
        components = mandatory_ui
        origin = "MANDATORY_DETERMINISTIC"
    elif active_capability in CAPABILITIES:
        capability = get_capability(active_capability)
        components, origin = validate_agent_a2ui(
            decision.get("uiProposal") or [], capability, state.get("toolResults", {})
        )
    else:
        # Reached with activeCapability=="CLARIFY" when clarify_node's
        # 3-strikes bounded-effort escalation routes here via escalate_node
        # — there's no registered Capability/tool catalog to validate
        # against, and escalate() always sets uiProposal=[] anyway.
        components, origin = [{"type": "welcome", "props": {}, "dataKey": None}], "DETERMINISTIC_FALLBACK"

    ui_mode = components[0]["type"] if components else "welcome"
    suggested_replies = _suggested_replies_for_finish(state, active_capability, mandatory_ui)

    state["a2uiComponents"] = components
    state["a2uiOrigin"] = origin
    state["uiState"] = {
        "uiMode": ui_mode,
        "assistantMessage": message,
        "canvasData": _build_canvas_data(state),
        "a2ui": components,
    }
    if suggested_replies:
        state["uiState"]["suggestedReplies"] = suggested_replies
    state["_mandatoryUi"] = None
    # escalate() (loop_safety.py) already sets status="ERROR" before this
    # node runs — don't clobber it back to "FINAL" if that happened.
    state["status"] = state.get("status") if state.get("status") == "ERROR" else "FINAL"

    _emit(
        state,
        agentAction="FINISH",
        a2uiProposed=decision.get("uiProposal"),
        a2uiOrigin=origin,
        retryOrError=state.get("_escalationReason"),
        finalOutcome=state["status"],
    )

    return state


def escalate_node(state: AgentStateV2) -> AgentStateV2:
    """
    Single shared escalation path (plan section 30) — reached only via
    routing, never invoked as a plain function from inside a conditional
    edge (conditional-edge-function mutations aren't reliably committed by
    LangGraph; only a real node's return value is). Derives its own reason
    when one wasn't already set by execute_tool_node's retry-limit check.
    """

    if not state.get("_escalationReason"):
        loop_safety.escalate(state, "max_iterations")
    else:
        loop_safety.escalate(state, state["_escalationReason"])

    return state


def route_after_agent_reason(state: AgentStateV2) -> str:
    if loop_safety.iteration_budget_exceeded(state):
        return "escalate"

    decision = state.get("_decision", {})
    action = decision.get("action")

    if action == "CALL_TOOL":
        capability = get_capability(state["activeCapability"])
        if decision.get("toolName") in capability.sensitive_tool_names:
            # Decided on the EDGE, before execute_tool ever runs (plan
            # section 15) — a sensitive tool call always goes through
            # confirmation, never straight to execution.
            return "request_confirmation"
        return "execute_tool"
    if action == "ASK_CUSTOMER":
        return "ask_customer"

    return "finish"


def route_after_execute_tool(state: AgentStateV2) -> str:
    if state.get("_escalationReason"):
        return "escalate"
    if loop_safety.iteration_budget_exceeded(state):
        return "escalate"

    return "agent_reason"


def route_after_ask_customer(state: AgentStateV2) -> str:
    if state.get("_pendingPivot"):
        return "enforce_capability_switch"
    if state.get("_reAsk"):
        return "ask_customer"
    if state.get("activeCapability") == "CLARIFY":
        # CLARIFY was never a real capability to "continue" into —
        # agent_reason has no tool catalog for it. The customer's answer
        # (now in state["userMessage"]) needs a genuine re-classification,
        # exactly like a fresh turn would get, so it can resolve to a real
        # capability (or loop back into clarify_node again if still vague).
        return "classify_capability"

    return "agent_reason"


def route_after_request_confirmation(state: AgentStateV2) -> str:
    if state.get("_escalationReason"):
        return "escalate"
    if state.get("_confirmationDryRunFailed"):
        return "agent_reason"
    if state.get("_pendingPivot"):
        return "enforce_capability_switch"
    if state.get("_confirmationReminder"):
        return "request_confirmation"

    return "execute_confirmed_action"


def route_after_execute_confirmed_action(state: AgentStateV2) -> str:
    if state.get("_confirmationInvalid"):
        return "agent_reason"
    if state.get("_confirmationDeclined"):
        return "agent_reason"

    return "finish"


def build_graph():
    graph = StateGraph(AgentStateV2)

    graph.add_node("classify_capability", classify_capability_node)
    graph.add_node("enforce_capability_switch", enforce_capability_switch_node)
    graph.add_node("agent_reason", agent_reason_node)
    graph.add_node("execute_tool", execute_tool_node)
    graph.add_node("ask_customer", ask_customer_node)
    graph.add_node("request_confirmation", request_confirmation_node)
    graph.add_node("execute_confirmed_action", execute_confirmed_action_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("finish", finish_node)
    graph.add_node("unsupported", unsupported_node)
    graph.add_node("clarify", clarify_node)

    graph.set_entry_point("classify_capability")
    graph.add_edge("classify_capability", "enforce_capability_switch")

    graph.add_conditional_edges(
        "enforce_capability_switch",
        route_after_capability_switch,
        {
            "agent_reason": "agent_reason",
            "unsupported": "unsupported",
            "clarify": "clarify",
        },
    )
    graph.add_edge("unsupported", END)
    graph.add_conditional_edges(
        "clarify",
        route_after_clarify,
        {"ask_customer": "ask_customer", "escalate": "escalate"},
    )

    graph.add_conditional_edges(
        "agent_reason",
        route_after_agent_reason,
        {
            "execute_tool": "execute_tool",
            "ask_customer": "ask_customer",
            "request_confirmation": "request_confirmation",
            "finish": "finish",
            "escalate": "escalate",
        },
    )
    graph.add_conditional_edges(
        "execute_tool",
        route_after_execute_tool,
        {"agent_reason": "agent_reason", "escalate": "escalate"},
    )
    graph.add_conditional_edges(
        "ask_customer",
        route_after_ask_customer,
        {
            "enforce_capability_switch": "enforce_capability_switch",
            "ask_customer": "ask_customer",
            "agent_reason": "agent_reason",
            "classify_capability": "classify_capability",
        },
    )
    graph.add_conditional_edges(
        "request_confirmation",
        route_after_request_confirmation,
        {
            "agent_reason": "agent_reason",
            "enforce_capability_switch": "enforce_capability_switch",
            "request_confirmation": "request_confirmation",
            "execute_confirmed_action": "execute_confirmed_action",
            "escalate": "escalate",
        },
    )
    graph.add_conditional_edges(
        "execute_confirmed_action",
        route_after_execute_confirmed_action,
        {"agent_reason": "agent_reason", "finish": "finish"},
    )
    graph.add_edge("escalate", "finish")
    graph.add_edge("finish", END)

    return graph.compile(checkpointer=InMemorySaver())


v2_agent_graph = build_graph()
