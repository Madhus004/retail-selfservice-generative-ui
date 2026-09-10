# agent/v3/graph.py
#
# Phase 1: ORDER_STATUS, V3's first real capability. Extends the Phase 0
# skeleton (classify -> enforce_switch -> agent_reason -> finish) with a
# real agent/tool loop: execute_tool, ask_customer (a real interrupt()),
# and workflow-stage-gated deterministic reasoning for ORDER_STATUS —
# same overall shape V2 proved out, rebuilt on AgentStateV3's corrected
# schema. Non-ORDER_STATUS messages still route to the Phase-0-style
# GENERAL_ASSISTANCE acknowledgment; Phase 2 gives that real teeth.
#
# The two schema fixes this whole rebuild exists for, both load-bearing
# throughout this file:
#   1. `messages` is the one authoritative history — every node returns
#      only the NEW message(s) for the add_messages reducer to append,
#      never the full accumulated list. See _messages_for_decision().
#   2. `toolCallLog` is an ordered list, not a dict keyed by tool name —
#      see latest_tool_result(). A second call to the same tool for a
#      different order can never again silently overwrite the first.

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import HTTPException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.config import get_config
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from tools import read_policy_file

from v3 import confirmation, idempotency, loop_safety
from v3.capabilities.registry import CAPABILITIES, get_capability
from v3.classifier import ClassificationContext, classify, extract_order_number
from v3.db import get_checkpointer
from v3.observability import Stopwatch, TraceRecord, emit, now_iso
from v3.state import AgentStateV3, PendingAction, ToolCallRecord
from v3.tools.cancellation_tools import validate_cancellation_proposal
from v3.tools.returns_tools import build_return_preview
from v3.ui.catalog import WELCOME, build_mandatory_ui, resolve_ui_mode, validate_components

load_dotenv()

# Stages where the next step is UNAMBIGUOUS — never left to the LLM's own
# judgment. Mostly "ask the customer to choose something" stages, plus one
# "the next action is unambiguously a specific tool call" stage
# (RETURNS' NEED_ELIGIBILITY_CHECK — added after a real, live-reproduced
# bug: with no mandatory gate, the real LLM sometimes skipped calling
# get_return_eligible_items_tool entirely and just narrated a plausible-
# sounding "which items would you like to return?" question from context,
# producing a text-only FINISH with no real interrupt behind it, directly
# violating its own system prompt's "never invent eligibility/items"
# instruction). Most other "which tool do I need first" stages
# (NEED_ORDER_FETCH, NEED_STATUS_LOOKUP, ELIGIBILITY_REQUIRED,
# READY_TO_ANSWER) deliberately stay LLM-driven — the LLM may have already
# resolved them from free text ("where is U-1002?" names the order
# directly) and a forced call there would fight the customer's own
# message instead of using it; NEED_ELIGIBILITY_CHECK is different because
# by the time it's reached, an order is already resolved and the very
# next step is always the same single tool call, never a judgment call.
_MANDATORY_ASK_STAGES = {
    "WAITING_FOR_ORDER_SELECTION",
    "WAITING_FOR_ITEM_SELECTION",
    "WAITING_FOR_REASON",
    "WAITING_FOR_METHOD",
    "NEED_ELIGIBILITY_CHECK",
}

# PendingAction.actionType <-> the tool that actually performs it, and the
# capability-declared sensitive tool name that triggers confirmation for
# it — same table shape V2 proved out (v2/graph.py's _SENSITIVE_ACTION_TYPES).
_SENSITIVE_ACTION_TYPES = {
    "submit_order_cancellation_tool": "SUBMIT_CANCELLATION",
    "create_return_tool": "CREATE_RETURN",
}
_ACTION_TYPE_TO_TOOL_NAME = {v: k for k, v in _SENSITIVE_ACTION_TYPES.items()}

# Fixed options for RETURNS' reason stage — no tool call needed (there's no
# per-order variation), but still a single source of truth rather than
# duplicated between backend validation and frontend copy.
RETURN_REASON_OPTIONS = ["Wrong size/fit", "Changed my mind", "Defective/damaged", "Other"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _current_run_id() -> str:
    try:
        return get_config()["configurable"].get("run_id", "unknown")
    except RuntimeError:
        return "unknown"


def _emit(state: AgentStateV3, **kwargs: Any) -> None:
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


def latest_tool_result(state: AgentStateV3, tool_name: str) -> Optional[Any]:
    """
    The one place deterministic reasoning reads "the most recent result
    for this tool" — the same convenience V2's toolResults dict gave, but
    without that dict's overwrite-hides-history problem: the full ordered
    log underneath is never lost, this just reads its tail.
    """

    for record in reversed(state.get("toolCallLog", [])):
        if record["toolName"] == tool_name and not record.get("error"):
            return record["resultSummary"]
    return None


def latest_record_for_order(state: AgentStateV3, tool_name: str, order_number: str) -> Optional[ToolCallRecord]:
    """
    The most recent toolCallLog entry for this EXACT (tool, order_number)
    pair — success or failure. This is what makes "have I already dealt
    with THIS order" a precise question instead of "have I ever called
    this tool," so a later message naming a DIFFERENT order (with no
    capability switch to reset toolCallLog) is never answered from a
    stale success, and a FAILED lookup for this order is recognized as a
    definitive (if unhappy) outcome instead of being silently retried
    forever.
    """

    for record in reversed(state.get("toolCallLog", [])):
        if record["toolName"] == tool_name and record.get("argsSummary", {}).get("order_number") == order_number:
            return record
    return None


def _latest_human_text(state: AgentStateV3) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return message.content
    return ""


def _resolve_order_number(state: AgentStateV3) -> Optional[str]:
    """
    A best-guess order number for this turn — from the classifier's
    extraction, or (only right after a genuine cross-capability switch)
    the last order any tool call actually resolved. This is a HINT, not a
    validated fact: callers that have a specific eligible-orders list to
    check against (RETURNS' _returns_stage/_deterministic_returns) must
    confirm this value is actually IN that list before treating it as
    resolved — the classifier can infer/carry an order from conversation
    context that isn't actually eligible for what this capability does
    (e.g. the order a customer just finished cancelling isn't return-
    eligible), and silently trusting it would skip the order-selection ask
    entirely instead of asking or correctly reporting ineligibility.
    """

    classification = state.get("_classification") or {}
    order_number = classification.get("orderNumber") or extract_order_number(_latest_human_text(state))

    if not order_number:
        # Only right after a GENUINE cross-capability switch (from != to) —
        # a same-capability "switch" carries no cross-capability order-
        # continuity intent (this exact guard is a fix carried forward
        # from a real V2 bug: a same-capability transition silently reused
        # a stale order the customer had just asked to move on from).
        transition = state.get("capabilityTransition")
        if transition and transition.get("from") != transition.get("to"):
            order_number = state.get("lastKnownOrderNumber")

    return order_number


def _build_canvas_data(state: AgentStateV3) -> Dict[str, Any]:
    """
    The one place a turn's renderable data is assembled — every a2ui
    component's dataKey names a toolCallLog tool, but the FRONTEND reads
    the actual values from here, not from toolCallLog directly. Every
    capability that offers a component referencing fetched data must add
    its tool's result here, or the frontend has nothing to render against
    (a real gap caught late: CANCELLATION/RETURNS shipped canvasData={}
    for their ask/propose stages until this was extended past Phase 1's
    ORDER_STATUS-only fields).
    """

    canvas: Dict[str, Any] = {}

    recent = latest_tool_result(state, "get_recent_orders_tool")
    if recent:
        canvas["customer"] = recent.get("customer")
        canvas["orders"] = recent.get("orders")

    status = latest_tool_result(state, "get_order_status_tool")
    if status:
        canvas["customer"] = status.get("customer", canvas.get("customer"))
        canvas["selectedOrder"] = status

    eligible_cancellations = latest_tool_result(state, "get_cancellation_eligible_orders_tool")
    if eligible_cancellations:
        canvas["customer"] = eligible_cancellations.get("customer", canvas.get("customer"))
        canvas["eligibleOrders"] = eligible_cancellations.get("orders")

    return_eligible_orders = latest_tool_result(state, "get_return_eligible_orders_tool")
    if return_eligible_orders:
        canvas["customer"] = return_eligible_orders.get("customer", canvas.get("customer"))
        # A separate key from "orders" (ORDER_STATUS's) — RETURNS' order
        # list is pre-filtered to return-eligible orders only, and a
        # capability switch never resets canvasData mid-render, so the two
        # must never be conflated.
        canvas["returnEligibleOrders"] = return_eligible_orders.get("orders")

    return_eligibility = latest_tool_result(state, "get_return_eligible_items_tool")
    if return_eligibility:
        canvas["returnEligibility"] = return_eligibility
        if return_eligibility.get("eligible"):
            canvas["returnReasonOptions"] = list(RETURN_REASON_OPTIONS)

    return canvas


def _messages_for_decision(decision: Dict[str, Any], capability=None) -> List[BaseMessage]:
    """
    Every branch of agent_reason_node funnels through here so `messages`
    always reflects exactly what the customer will see, with no separate
    bookkeeping step to remember (V2 needed _record_conversation_turn
    calls scattered across every exit point; returning the AIMessage as
    part of the node's own return value makes the reducer capture it
    automatically).

    CALL_TOOL decisions reached WITHOUT a real LLM call (the mandatory
    gate, the structured-selection fast path) synthesize an AIMessage
    with a locally-generated tool_call id — execute_tool_node's
    ToolMessage correlates against it — so `messages` stays a valid,
    protocol-correct transcript regardless of whether a call was
    LLM-decided or code-decided.

    A CALL_TOOL decision for a SENSITIVE tool is the one exception: that
    call never reaches execute_tool_node (agent_reason routes it to
    request_confirmation instead, see route_after_agent_reason), so a
    synthesized tool_calls AIMessage here would dangle forever with no
    ToolMessage ever answering it — a protocol violation the OpenAI API
    would reject on a later call. Treated like ASK_CUSTOMER/FINISH
    instead: a plain AIMessage carrying the propose text (e.g. "I'll
    cancel that. Let's confirm."), since the confirmation step itself is
    conceptually a pause for customer input, not a completed tool call.
    """

    action = decision.get("action")
    tool_name = decision.get("toolName")
    is_sensitive = bool(capability) and tool_name in capability.sensitive_tool_names

    if action == "CALL_TOOL" and not is_sensitive:
        return [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "name": tool_name,
                        "args": decision.get("toolArgs") or {},
                    }
                ],
            )
        ]

    if decision.get("message"):
        return [AIMessage(content=decision["message"])]

    return []


def _policy_text_for(capability) -> str:
    contents = [read_policy_file(name) for name in capability.policy_files]
    return "\n\n---\n\n".join(text for text in contents if text)


def _build_capability_system_message(capability) -> SystemMessage:
    system_text = capability.system_prompt
    policy_text = _policy_text_for(capability)
    if policy_text:
        system_text += (
            "\n\nRelevant policy, for your own reasoning only — never quote "
            "internal policy mechanics to the customer:\n" + policy_text
        )
    return SystemMessage(system_text)


# ---------------------------------------------------------------------------
# ORDER_STATUS — workflow-stage derivation + deterministic reasoning
# ---------------------------------------------------------------------------


def _order_status_stage(state: AgentStateV3) -> str:
    order_number = _resolve_order_number(state)

    # A definitive outcome (success OR error) for THIS order only —
    # otherwise a later message naming a DIFFERENT order (with no
    # capability switch in between, so toolCallLog was never reset) would
    # silently answer from a different order's stale cache, and a FAILED
    # lookup for this order would be retried forever instead of being
    # recognized as done. toolCallLog itself is never at fault — it
    # correctly keeps every entry — this is what makes reading it precise.
    if order_number and latest_record_for_order(state, "get_order_status_tool", order_number):
        return "READY_TO_ANSWER"

    if order_number:
        return "NEED_STATUS_LOOKUP"

    recent = latest_tool_result(state, "get_recent_orders_tool")
    if recent:
        orders = recent.get("orders") or []
        if len(orders) > 1:
            return "WAITING_FOR_ORDER_SELECTION"
        return "NEED_STATUS_LOOKUP"

    return "NEED_ORDER_FETCH"


def _cancellation_stage(state: AgentStateV3) -> str:
    eligible = latest_tool_result(state, "get_cancellation_eligible_orders_tool")
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

    cancellable_items = [item for item in selected_order.get("items", []) if item.get("cancellableQuantity", 0) > 0]

    if not cancellable_items:
        return "NOTHING_LEFT_TO_CANCEL"

    if state.get("_selectedLineItems") is None and len(cancellable_items) > 1:
        return "WAITING_FOR_ITEM_SELECTION"

    return "READY_TO_PROPOSE"


def _return_eligibility_for_resolved_order(state: AgentStateV3) -> Optional[Any]:
    """
    The return-eligibility result for the order CURRENTLY resolved this
    turn — never just "whichever get_return_eligible_items_tool call
    happened most recently." Real bug this closes: once that tool had been
    called for one order (even a stale, carried-over one that turned out
    ineligible), latest_tool_result kept returning that same ineligible
    result on every later turn regardless of what the customer did next —
    a fresh get_return_eligible_orders_tool fetch for a real order list
    was never even considered, because the ineligible record for the OLD
    order never stopped being "the latest." Scoping to the resolved order
    number (like _order_status_stage already does via
    latest_record_for_order) means a mismatched or superseded order simply
    reads as "no eligibility fetched for this order yet," correctly
    falling through to the orders-list logic below.
    """

    order_number = _resolve_order_number(state)
    if not order_number:
        return None
    record = latest_record_for_order(state, "get_return_eligible_items_tool", order_number)
    if not record or record.get("error"):
        return None
    return record["resultSummary"]


def _returns_stage(state: AgentStateV3) -> str:
    eligibility = _return_eligibility_for_resolved_order(state)

    if not eligibility:
        eligible_orders_result = latest_tool_result(state, "get_return_eligible_orders_tool")

        if not eligible_orders_result:
            # Nothing fetched yet this turn — a resolved order number
            # (explicit in the message, or carried over from a different
            # capability) is safe to trust here: the next step is always
            # get_return_eligible_items_tool, which is self-validating —
            # it returns eligible:false gracefully for a wrong or
            # ineligible order, never a false success.
            if _resolve_order_number(state):
                return "NEED_ELIGIBILITY_CHECK"
            return "NEED_ORDER_FETCH"

        # Once the eligible-orders LIST is fetched, a resolved order
        # number is only trusted as "the one meant" if it's actually IN
        # that list. Real bug this closes: RETURNS' own real-LLM reasoning
        # (which only ever sees `messages`, never the classification
        # scratch field) can independently decide to fetch the general
        # order list without knowing an order was already "resolved" —
        # and the classifier itself can infer/carry an order number from
        # conversation context that isn't actually return-eligible (e.g.
        # the order a customer just finished cancelling). Once real data
        # is in hand, that mismatch must always fall through to a genuine
        # order-selection ask, never silently answer about the wrong
        # order or skip straight past the mandatory-ask gate.
        orders = (eligible_orders_result or {}).get("orders") or []
        order_number = _resolve_order_number(state)
        matched_order = next((o for o in orders if o.get("orderNumber") == order_number), None)

        if matched_order:
            return "NEED_ELIGIBILITY_CHECK"
        if len(orders) > 1:
            return "WAITING_FOR_ORDER_SELECTION"
        if not orders:
            return "NO_ELIGIBLE_ORDERS"
        return "NEED_ELIGIBILITY_CHECK"

    if not eligibility.get("eligible"):
        return "INELIGIBLE"

    returnable_items = [item for item in (eligibility.get("items") or []) if item.get("returnableQuantity", 0) > 0]

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


def _compute_workflow_stage(state: AgentStateV3) -> str:
    """
    Derived fresh from state every time, never persisted. Defensively
    coded (never raises): this feeds every trace record, so a bug here
    must never take down the graph execution it's merely describing.
    """

    try:
        pending = state.get("pendingAction")
        capability_name = state.get("activeCapability")

        # A pendingAction only reflects the CURRENT capability's in-flight
        # action — guard carried forward from V2's own hard-won fix (a
        # stale, already-finished pendingAction from a PREVIOUS capability
        # must never make every workflow stage compute as COMPLETED).
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
        return capability_name or "UNKNOWN"
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _compute_offered_candidates(state: AgentStateV3) -> Dict[str, Any]:
    candidates: Dict[str, Any] = {}
    order_numbers: List[str] = []

    for tool_name in (
        "get_recent_orders_tool",
        "get_cancellation_eligible_orders_tool",
        "get_return_eligible_orders_tool",
    ):
        source = latest_tool_result(state, tool_name)
        if source and source.get("orders"):
            order_numbers = [o["orderNumber"] for o in source["orders"] if o.get("orderNumber")]
            break

    candidates["orderNumbers"] = order_numbers

    order_number = _resolve_order_number(state)
    eligible = latest_tool_result(state, "get_cancellation_eligible_orders_tool")
    eligible_orders = (eligible or {}).get("orders") or []
    selected_cancellation_order = next(
        (o for o in eligible_orders if o.get("orderNumber") == order_number), None
    )
    if selected_cancellation_order:
        candidates["items"] = {
            item["orderLineId"]: {"maxQuantity": item.get("cancellableQuantity", 0)}
            for item in selected_cancellation_order.get("items", [])
        }

    return_eligibility = latest_tool_result(state, "get_return_eligible_items_tool")
    if return_eligibility and return_eligibility.get("eligible"):
        candidates["items"] = {
            item["orderLineId"]: {"maxQuantity": item.get("returnableQuantity", 0)}
            for item in return_eligibility.get("items", [])
        }
        candidates["reasons"] = list(RETURN_REASON_OPTIONS)
        candidates["methods"] = list(return_eligibility.get("returnMethods") or [])

    return candidates


def _deterministic_order_status(state: AgentStateV3) -> Dict[str, Any]:
    order_number = _resolve_order_number(state)
    record = latest_record_for_order(state, "get_order_status_tool", order_number) if order_number else None

    # Same order-number-precision as _order_status_stage — a record for a
    # DIFFERENT order than the one just resolved must never be reused (see
    # that function's comment). A FAILED lookup for THIS order is a
    # definitive outcome too — answered with an apology, never retried.
    if record and record.get("error"):
        return {
            "action": "FINISH",
            "message": f"I couldn't find an order matching {order_number} — could you double-check the order number?",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    if record:
        status = record["resultSummary"]
        summary = status.get("summary", {}) if isinstance(status, dict) else {}
        message = summary.get("customerMessage") or "Here's the latest status for your order."
        return {"action": "FINISH", "message": message, "toolName": None, "toolArgs": {}, "uiProposal": []}

    if order_number:
        return {
            "action": "CALL_TOOL",
            "toolName": "get_order_status_tool",
            "toolArgs": {"order_number": order_number},
            "message": "",
            "uiProposal": [],
        }

    recent = latest_tool_result(state, "get_recent_orders_tool")
    if recent:
        orders = recent.get("orders") or []

        if len(orders) == 1:
            return {
                "action": "CALL_TOOL",
                "toolName": "get_order_status_tool",
                "toolArgs": {"order_number": orders[0]["orderNumber"]},
                "message": "",
                "uiProposal": [],
            }

        if len(orders) > 1:
            return {
                "action": "ASK_CUSTOMER",
                "message": "I found a few recent orders — which one would you like to check?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "ORDER_SELECTED",
                "uiProposal": [{"type": "OrderListPicker", "props": {}, "dataKey": "get_recent_orders_tool"}],
            }

        return {
            "action": "FINISH",
            "message": "I don't see any recent orders on this account.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    return {
        "action": "CALL_TOOL",
        "toolName": "get_recent_orders_tool",
        "toolArgs": {},
        "message": "",
        "uiProposal": [],
    }


def _deterministic_general_assistance(state: AgentStateV3) -> Dict[str, Any]:
    """
    General Assistance has no mandatory ask stages or structured
    selections — this only exists as the no-API-key fallback (matching
    every other capability's "must still work with no key" discipline).
    """

    return {
        "action": "FINISH",
        "message": (
            "Hi! I'm Uni. I can answer questions about our return, "
            "cancellation, and delivery policies — what would you like to know?"
        ),
        "toolName": None,
        "toolArgs": {},
        "uiProposal": [],
    }


def _deterministic_cancellation(state: AgentStateV3) -> Dict[str, Any]:
    if state.get("_confirmationDeclined"):
        state["_confirmationDeclined"] = False
        return {
            "action": "FINISH",
            "message": "No problem — I won't cancel that. Anything else I can help with?",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    eligible = latest_tool_result(state, "get_cancellation_eligible_orders_tool")

    if not eligible:
        return {
            "action": "CALL_TOOL",
            "toolName": "get_cancellation_eligible_orders_tool",
            "toolArgs": {},
            "message": "",
            "uiProposal": [],
        }

    orders = (eligible or {}).get("orders") or []

    if not orders:
        return {
            "action": "FINISH",
            "message": (
                "I don't see any orders that are still eligible to cancel — once an "
                "order ships, it can no longer be cancelled here."
            ),
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    order_number = _resolve_order_number(state)
    selected_order = next((o for o in orders if o.get("orderNumber") == order_number), None)

    if not selected_order:
        if len(orders) == 1:
            selected_order = orders[0]
        else:
            return {
                "action": "ASK_CUSTOMER",
                "message": "Which order would you like to cancel?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "ORDER_SELECTED",
                "uiProposal": [
                    {
                        "type": "CancellationOrderPicker",
                        "props": {},
                        "dataKey": "get_cancellation_eligible_orders_tool",
                    }
                ],
            }

    cancellable_items = [item for item in selected_order.get("items", []) if item.get("cancellableQuantity", 0) > 0]

    if not cancellable_items:
        return {
            "action": "FINISH",
            "message": f"There's nothing left to cancel on order {selected_order['orderNumber']}.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    selected_items = state.get("_selectedLineItems")

    if selected_items is not None:
        # An explicit ITEM_SELECTED resume already narrowed this down —
        # the sensitive tool's own preview/validation re-checks it
        # authoritatively either way.
        line_selections = selected_items
    elif len(cancellable_items) == 1:
        line_selections = [
            {"orderLineId": item["orderLineId"], "quantity": item["cancellableQuantity"]}
            for item in cancellable_items
        ]
    else:
        return {
            "action": "ASK_CUSTOMER",
            "message": f"Which items on order {selected_order['orderNumber']} would you like to cancel?",
            "toolName": None,
            "toolArgs": {},
            "interactionType": "ITEM_SELECTED",
            "uiProposal": [
                {
                    "type": "CancellationItemPicker",
                    "props": {},
                    "dataKey": "get_cancellation_eligible_orders_tool",
                }
            ],
        }

    return {
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


def _deterministic_returns(state: AgentStateV3) -> Dict[str, Any]:
    if state.get("_confirmationDeclined"):
        state["_confirmationDeclined"] = False
        return {
            "action": "FINISH",
            "message": "No problem — I won't return that. Anything else I can help with?",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    eligibility = _return_eligibility_for_resolved_order(state)

    if eligibility:
        if not eligibility.get("eligible"):
            return {
                "action": "FINISH",
                "message": eligibility.get("reason")
                or f"Order {eligibility.get('orderNumber')} isn't eligible for a return.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }

        returnable_items = [item for item in (eligibility.get("items") or []) if item.get("returnableQuantity", 0) > 0]

        if not returnable_items:
            return {
                "action": "FINISH",
                "message": f"There's nothing left to return on order {eligibility.get('orderNumber')}.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }

        selected_items = state.get("_selectedLineItems")

        if selected_items is None:
            if len(returnable_items) == 1:
                selected_items = [
                    {"orderLineId": item["orderLineId"], "quantity": item["returnableQuantity"]}
                    for item in returnable_items
                ]
            else:
                return {
                    "action": "ASK_CUSTOMER",
                    "message": f"Which items on order {eligibility['orderNumber']} would you like to return?",
                    "toolName": None,
                    "toolArgs": {},
                    "interactionType": "ITEM_SELECTED",
                    "uiProposal": [
                        {"type": "ReturnItemPicker", "props": {}, "dataKey": "get_return_eligible_items_tool"}
                    ],
                }

        reason = state.get("_selectedReason")

        if reason is None:
            return {
                "action": "ASK_CUSTOMER",
                "message": f"Why are you returning your order {eligibility['orderNumber']}?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "REASON_SELECTED",
                "uiProposal": [{"type": "ReturnReasonPrompt", "props": {}, "dataKey": None}],
            }

        available_methods = eligibility.get("returnMethods") or []
        method = state.get("_selectedReturnMethod")

        if method is None and len(available_methods) > 1:
            return {
                "action": "ASK_CUSTOMER",
                "message": f"How would you like to return order {eligibility['orderNumber']} — by mail or in-store?",
                "toolName": None,
                "toolArgs": {},
                "interactionType": "RETURN_METHOD_SELECTED",
                "uiProposal": [
                    {"type": "ReturnMethodPrompt", "props": {}, "dataKey": "get_return_eligible_items_tool"}
                ],
            }

        tool_args = {"order_number": eligibility["orderNumber"], "line_selections": selected_items, "reason": reason}
        if method is not None:
            tool_args["method"] = method

        return {
            "action": "CALL_TOOL",
            "toolName": "create_return_tool",
            "toolArgs": tool_args,
            "message": f"I'll submit that return for order {eligibility['orderNumber']}. Let's confirm.",
            "uiProposal": [],
        }

    eligible_orders_result = latest_tool_result(state, "get_return_eligible_orders_tool")

    if not eligible_orders_result:
        # Nothing fetched yet this turn — a resolved order number is safe
        # to trust here; get_return_eligible_items_tool is self-validating
        # (see _returns_stage's matching comment for the full rationale).
        order_number = _resolve_order_number(state)

        if order_number:
            return {
                "action": "CALL_TOOL",
                "toolName": "get_return_eligible_items_tool",
                "toolArgs": {"order_number": order_number},
                "message": "",
                "uiProposal": [],
            }

        return {
            "action": "CALL_TOOL",
            "toolName": "get_return_eligible_orders_tool",
            "toolArgs": {},
            "message": "",
            "uiProposal": [],
        }

    orders = (eligible_orders_result or {}).get("orders") or []

    if not orders:
        return {
            "action": "FINISH",
            "message": "I don't see any orders that are currently eligible for a return.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }

    if len(orders) == 1:
        return {
            "action": "CALL_TOOL",
            "toolName": "get_return_eligible_items_tool",
            "toolArgs": {"order_number": orders[0]["orderNumber"]},
            "message": "",
            "uiProposal": [],
        }

    # The eligible-orders LIST is fetched — a resolved order number is
    # only trusted as "the one meant" if it's actually IN that list (see
    # _returns_stage's matching comment for the bug this closes).
    order_number = _resolve_order_number(state)
    matched_order = next((o for o in orders if o.get("orderNumber") == order_number), None)

    if matched_order:
        return {
            "action": "CALL_TOOL",
            "toolName": "get_return_eligible_items_tool",
            "toolArgs": {"order_number": matched_order["orderNumber"]},
            "message": "",
            "uiProposal": [],
        }

    return {
        "action": "ASK_CUSTOMER",
        "message": "Which order would you like to return an item from?",
        "toolName": None,
        "toolArgs": {},
        "interactionType": "ORDER_SELECTED",
        "uiProposal": [{"type": "OrderListPicker", "props": {}, "dataKey": "get_return_eligible_orders_tool"}],
    }


def _deterministic_agent_reason(state: AgentStateV3, capability) -> Dict[str, Any]:
    if capability.name == "ORDER_STATUS":
        return _deterministic_order_status(state)
    if capability.name == "GENERAL_ASSISTANCE":
        return _deterministic_general_assistance(state)
    if capability.name == "CANCELLATION":
        return _deterministic_cancellation(state)
    if capability.name == "RETURNS":
        return _deterministic_returns(state)
    raise ValueError(f"No deterministic handler registered for capability {capability.name!r}")


def _apply_structured_selection(state: AgentStateV3, selection: Dict[str, Any]) -> AgentStateV3:
    """
    Merges a validated structured selection into scratch state — NEVER
    into `messages`. This is what keeps a click from ever being
    reinterpreted as prose, and just as importantly keeps `messages` free
    of any scalar a later turn could forget to refresh (the exact defect
    that motivated this rebuild).
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


def _validate_structured_payload(interaction_type: str, payload: Dict[str, Any], candidates: Dict[str, Any]):
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


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def classify_capability_node(state: AgentStateV3) -> AgentStateV3:
    stopwatch = Stopwatch()

    # recentTurnsSummary comes straight from messages — no second
    # hand-maintained summary field the way V2's conversationSummary was.
    # The current message is excluded (classify()'s own first argument
    # already carries it) so this is "what came before," not an echo.
    turn_texts = [
        f"{'assistant' if isinstance(m, AIMessage) else 'user'}: {m.content}"
        for m in state.get("messages", [])
        if isinstance(m, (HumanMessage, AIMessage)) and m.content
    ]
    recent_turns = turn_texts[:-1] if turn_texts else []

    context = ClassificationContext(
        activeCapability=state.get("activeCapability"),
        recentTurnsSummary=recent_turns,
    )
    classification = classify(_latest_human_text(state), context)
    state["_classification"] = classification.model_dump()

    _emit(
        state,
        agentAction="CLASSIFY",
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini") if os.getenv("OPENAI_API_KEY") else "deterministic-fallback",
        latencyMs=stopwatch.elapsed_ms(),
    )
    return state


def enforce_capability_switch_node(state: AgentStateV3) -> AgentStateV3:
    classification = state.get("_classification") or {}
    requested_capability = classification.get("capability") or "GENERAL_ASSISTANCE"
    old_capability = state.get("activeCapability")
    is_switch_attempt = bool(classification.get("isCapabilitySwitch"))

    switched = bool(old_capability) and (is_switch_attempt or requested_capability != old_capability)

    if switched:
        state["previousCapability"] = old_capability
        state["capabilityTransition"] = {"from": old_capability, "to": requested_capability}
        state["toolCallLog"] = []
        state["loopIteration"] = 0
        # Structured-selection scratch state is capability-specific — an
        # ITEM_SELECTED payload's orderLineIds only mean something for the
        # order/capability they were validated against. Real bug this
        # closes (found live): cancelling U-1004 (which sets
        # _selectedLineItems to its one selected line) and then pivoting
        # to RETURNS left that stale selection in place, so RETURNS'
        # "has an item already been selected?" check saw a non-None value
        # and skipped its own item-selection ask entirely — jumping
        # straight to the reason prompt for an order it had never actually
        # asked about item quantities for.
        state["_selectedLineItems"] = None
        state["_selectedReason"] = None
        state["_selectedReturnMethod"] = None
    else:
        state["capabilityTransition"] = None

    state["activeCapability"] = requested_capability
    state.setdefault("toolCallLog", [])
    state.setdefault("loopIteration", 0)

    if switched:
        _emit(state, agentAction="SWITCH", capabilityTransition=state["capabilityTransition"])

    return state


def _unregistered_capability_fallback(state: AgentStateV3, stopwatch: Stopwatch) -> AgentStateV3:
    """
    Defensive-only, last-resort catch-all — every real classifier output
    is registered in CAPABILITIES as of Phase 2 (ORDER_STATUS and
    GENERAL_ASSISTANCE both exist for real), so this should never actually
    fire in normal operation. Kept so a future capability name mismatch
    degrades gracefully instead of crashing the graph with a KeyError.
    """

    message = "Hi! I'm Uni. Could you tell me more about what you need help with?"
    ai_message = AIMessage(content=message)
    state["_decision"] = {"action": "FINISH", "message": message}
    _emit(state, agentAction="FINISH", model="unregistered-capability-fallback", latencyMs=stopwatch.elapsed_ms())
    return {**state, "messages": [ai_message]}


def agent_reason_node(state: AgentStateV3) -> AgentStateV3:
    stopwatch = Stopwatch()
    active_capability = state.get("activeCapability")

    if active_capability not in CAPABILITIES:
        return _unregistered_capability_fallback(state, stopwatch)

    capability = get_capability(active_capability)

    structured_selection = state.get("_structuredSelection")
    if structured_selection:
        state["_structuredSelection"] = None
        state = _apply_structured_selection(state, structured_selection)
        decision = _deterministic_agent_reason(state, capability)
        state["_decision"] = decision
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
        return {**state, "messages": _messages_for_decision(decision, capability)}

    if state.get("_confirmationDeclined"):
        # A decline is never a judgment call for the LLM to make — always
        # handled deterministically, regardless of API key, so the
        # "don't propose the same sensitive action again" rule can never
        # be silently skipped by a real-LLM turn with no memory of the
        # decline (messages carries no ToolMessage/flag for it, unlike
        # V2's toolResults dict, which had a channel for this; the
        # deterministic gate makes that channel unnecessary here).
        decision = _deterministic_agent_reason(state, capability)
        state["_decision"] = decision
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model="deterministic-confirmation-declined",
            latencyMs=stopwatch.elapsed_ms(),
        )
        return {**state, "messages": _messages_for_decision(decision, capability)}

    workflow_stage = _compute_workflow_stage(state)

    if workflow_stage in _MANDATORY_ASK_STAGES:
        decision = _deterministic_agent_reason(state, capability)
        state["_decision"] = decision
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model="deterministic-workflow-gate",
            latencyMs=stopwatch.elapsed_ms(),
        )
        return {**state, "messages": _messages_for_decision(decision, capability)}

    if not os.getenv("OPENAI_API_KEY"):
        decision = _deterministic_agent_reason(state, capability)
        state["_decision"] = decision
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model="deterministic-fallback",
            latencyMs=stopwatch.elapsed_ms(),
        )
        return {**state, "messages": _messages_for_decision(decision, capability)}

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(
        model=model_name, temperature=0, max_tokens=300, timeout=loop_safety.LLM_TIMEOUT_SECONDS
    ).bind_tools(list(capability.tools))

    try:
        ai_message = llm.invoke([_build_capability_system_message(capability)] + state["messages"])
    except Exception as exc:  # noqa: BLE001
        print(f"[v3.graph] agent_reason failed, using deterministic fallback: {exc}")
        decision = _deterministic_agent_reason(state, capability)
        state["_decision"] = decision
        _emit(
            state,
            agentAction=decision.get("action"),
            requestedTool=decision.get("toolName"),
            model=model_name,
            retryOrError=str(exc),
            latencyMs=stopwatch.elapsed_ms(),
        )
        return {**state, "messages": _messages_for_decision(decision, capability)}

    usage = getattr(ai_message, "usage_metadata", None) or {}

    if not ai_message.tool_calls:
        decision = {
            "action": "FINISH",
            "message": ai_message.content or "I'm not sure how to help with that yet.",
            "toolName": None,
            "toolArgs": {},
            "uiProposal": [],
        }
    else:
        call = ai_message.tool_calls[0]
        tool_name = call.get("name")
        is_sensitive = tool_name in capability.sensitive_tool_names
        decision = {
            "action": "CALL_TOOL",
            "toolName": tool_name,
            "toolArgs": call.get("args") or {},
            # A sensitive call is routed to request_confirmation, never
            # execute_tool — its propose text has to travel through
            # decision.message (request_confirmation_node's own fallback
            # covers a blank one) since the real ai_message with its
            # tool_calls is never used for that path (see below).
            "message": (ai_message.content or "Let me get that ready to confirm.") if is_sensitive else "",
            "uiProposal": [],
        }

    state["_decision"] = decision
    _emit(
        state,
        agentAction=decision.get("action"),
        requestedTool=decision.get("toolName"),
        model=model_name,
        promptTokens=usage.get("input_tokens"),
        completionTokens=usage.get("output_tokens"),
        latencyMs=stopwatch.elapsed_ms(),
    )

    if decision["action"] == "CALL_TOOL" and decision["toolName"] in capability.sensitive_tool_names:
        # See _messages_for_decision's docstring: the raw ai_message's
        # tool_calls would dangle forever (request_confirmation_node
        # never produces a matching ToolMessage), so a plain propose
        # AIMessage is synthesized instead of using ai_message directly.
        return {**state, "messages": _messages_for_decision(decision, capability)}

    # ai_message is the REAL message from the model — already carries real
    # tool_calls with real ids for a non-sensitive CALL_TOOL, so it's used
    # directly rather than re-synthesized via _messages_for_decision.
    return {**state, "messages": [ai_message]}


def execute_tool_node(state: AgentStateV3) -> AgentStateV3:
    decision = state.get("_decision", {})
    tool_name = decision.get("toolName")
    tool_args = decision.get("toolArgs") or {}
    # Computed once, before the tool runs, so the SAME stage value scopes
    # both the repeated-call check and the signature it records.
    workflow_stage = _compute_workflow_stage(state)

    capability = get_capability(state["activeCapability"])
    tool_by_name = {t.name: t for t in capability.tools}

    # Correlate against the AIMessage that triggered this call — always
    # the last message by construction (agent_reason_node just appended
    # it, real or synthesized, immediately before routing here).
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    tool_call_id = tool_calls[0]["id"] if tool_calls else f"call_{uuid.uuid4().hex[:24]}"

    call_id = str(uuid.uuid4())
    started_at = now_iso()
    stopwatch = Stopwatch()

    if tool_name not in tool_by_name:
        error = f"Tool '{tool_name}' is not available for capability {capability.name}."
        return _finish_tool_call(state, call_id, tool_name or "unknown", tool_args, None, error, started_at, tool_call_id, stopwatch)

    if tool_name in capability.sensitive_tool_names:
        # Defense in depth — no sensitive tools exist for ORDER_STATUS yet
        # (Phase 3+ adds real ones and the request_confirmation routing
        # that keeps this branch actually unreachable in normal operation).
        error = f"Tool '{tool_name}' is sensitive and must go through confirmation — it cannot be called directly."
        return _finish_tool_call(state, call_id, tool_name, tool_args, None, error, started_at, tool_call_id, stopwatch)

    if loop_safety.is_repeated_call(state, tool_name, tool_args, workflow_stage):
        note = (
            "This exact request was already made twice this turn — use the "
            "existing result or ask the customer instead of repeating it."
        )
        return _finish_tool_call(
            state, call_id, tool_name, tool_args, {"note": note}, "repeated_call_short_circuited",
            started_at, tool_call_id, stopwatch,
        )

    try:
        result = loop_safety.run_with_timeout(
            lambda: tool_by_name[tool_name].invoke(tool_args), loop_safety.TOOL_TIMEOUT_SECONDS
        )
        error = None
    except Exception as exc:  # noqa: BLE001 - tool failures (incl. timeouts) are surfaced, not swallowed
        result = {"error": str(exc)}
        error = str(exc)

    loop_safety.record_call_signature(state, tool_name, tool_args, workflow_stage)

    if error:
        failures = loop_safety.consecutive_failure_count(state, tool_name)
        if failures > loop_safety.MAX_RETRIES_PER_TOOL:
            loop_safety.escalate(state, f"tool_retry_limit_exceeded:{tool_name}")

    if not error and tool_args.get("order_number"):
        # Survives capability switches (AgentStateV3.lastKnownOrderNumber)
        # so a genuine cross-capability pivot can carry the order forward
        # instead of re-asking.
        state["lastKnownOrderNumber"] = tool_args["order_number"]

    return _finish_tool_call(state, call_id, tool_name, tool_args, result, error, started_at, tool_call_id, stopwatch)


def _finish_tool_call(
    state: AgentStateV3,
    call_id: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Optional[Any],
    error: Optional[str],
    started_at: str,
    tool_call_id: str,
    stopwatch: Stopwatch,
) -> AgentStateV3:
    record: ToolCallRecord = {
        "callId": call_id,
        "toolName": tool_name,
        "argsSummary": tool_args,
        "resultSummary": result,
        "isSensitive": False,
        "startedAt": started_at,
        "finishedAt": now_iso(),
        "error": error,
    }
    tool_message = ToolMessage(content=json.dumps(result, default=str), tool_call_id=tool_call_id, name=tool_name)

    # toolCallLog is a PLAIN channel (no reducer) — the full new list must
    # be returned (old + new), unlike `messages` below, which only ever
    # wants the delta. Mixing these two conventions up is exactly the
    # class of bug this schema exists to make impossible to write by
    # accident — spelled out here on purpose.
    updated_log = state.get("toolCallLog", []) + [record]

    _emit(
        state,
        agentAction="CALL_TOOL",
        requestedTool=tool_name,
        toolInputSummary=tool_args,
        toolResultSummary=result,
        retryOrError=error,
        latencyMs=stopwatch.elapsed_ms(),
    )

    return {
        **state,
        "toolCallLog": updated_log,
        "messages": [tool_message],
        "loopIteration": state.get("loopIteration", 0) + 1,
    }


def ask_customer_node(state: AgentStateV3) -> AgentStateV3:
    """
    Real interrupt()-based pause. Per LangGraph's interrupt() semantics,
    on resume the graph re-executes this node FROM THE TOP — everything
    above the interrupt() call re-runs (idempotently, recomputed from
    state) before the resumed value is available.
    """

    decision = state.get("_decision", {})
    active_capability = state.get("activeCapability")

    if active_capability in CAPABILITIES:
        capability = get_capability(active_capability)
        components, origin = validate_components(
            decision.get("uiProposal"), capability, state.get("toolCallLog", [])
        )
    else:
        components, origin = [{"type": WELCOME, "props": {}, "dataKey": None}], "DETERMINISTIC_FALLBACK"

    question = decision.get("message") or "Could you tell me more?"
    expected_interaction_type = decision.get("interactionType", "FREEFORM")
    candidates = _compute_offered_candidates(state)

    interrupt_ui_state = {
        "uiMode": resolve_ui_mode(components),
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

    resumed_type = resumed.get("type") if isinstance(resumed, dict) else None

    if resumed_type is not None:
        payload = resumed.get("payload") or {}

        if resumed_type != expected_interaction_type:
            state["_decision"] = {**decision, "message": question}
            state["_reAsk"] = True
            _emit(
                state,
                agentAction="RESUME",
                interruptType="ASK_CUSTOMER",
                interactionType=resumed_type,
                interactionSource="A2UI",
                validatedAgainstCandidates=False,
                retryOrError="interaction_type_mismatch",
            )
            return state

        ok, corrective_message = _validate_structured_payload(resumed_type, payload, candidates)

        if not ok:
            state["_decision"] = {**decision, "message": corrective_message}
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

        state["_structuredSelection"] = {"type": resumed_type, "payload": payload}
        state["_reAsk"] = False
        _emit(
            state,
            agentAction="RESUME",
            interruptType="ASK_CUSTOMER",
            interactionType=resumed_type,
            interactionSource="A2UI",
            selectionSummary=payload,
            validatedAgainstCandidates=True,
        )
        return state

    # Free text (Phase 1 simplification — no capability-pivot sophistication
    # yet, see router.py; that lands in Phase 2 once a second real
    # capability exists to pivot into, same phasing V2 used).
    customer_reply = resumed.get("customerReply") if isinstance(resumed, dict) else resumed
    state["_reAsk"] = False
    _emit(state, agentAction="ASK_CUSTOMER", interruptType="ASK_CUSTOMER", interactionSource="FREE_TEXT")
    return {**state, "messages": [HumanMessage(content=customer_reply or "")]}


def _validate_sensitive_proposal(state: AgentStateV3, tool_name: Optional[str], tool_args: Dict[str, Any]):
    """
    Validates a proposed sensitive action WITHOUT ever calling the
    mutation-shaped tool itself — submit_order_cancellation_tool only ever
    runs once, from execute_confirmed_action_node, after a valid Confirm.
    CANCELLATION's own validate_cancellation_proposal validates against
    THIS turn's already-fetched get_cancellation_eligible_orders_tool
    result, never re-deriving eligibility rules from scratch.

    Returns (ok, preview_dict_or_None, error_message_or_None). The preview
    dict, when present, has no transaction id and no "status" field —
    nothing that could ever look like a completed submission, because
    nothing here ever calls the function that mints one.
    """

    try:
        if tool_name == "submit_order_cancellation_tool":
            eligible = latest_tool_result(state, "get_cancellation_eligible_orders_tool")
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
    except HTTPException as exc:
        return False, None, str(exc.detail)

    return False, None, f"Unknown sensitive action: {tool_name}"


def request_confirmation_node(state: AgentStateV3) -> AgentStateV3:
    """
    Real interrupt()-based pause for a sensitive action — reached only via
    the routing edge after agent_reason (never called for a non-sensitive
    tool). Validates the proposal via _validate_sensitive_proposal, which
    NEVER calls the underlying mutation-shaped tool, so nothing before the
    interrupt() call below can ever generate a transaction id or claim a
    submission succeeded; only execute_confirmed_action_node, after a
    valid Confirm, does that.

    Like ask_customer_node, this re-executes from the top on every resume,
    so pendingAction's actionId is derived deterministically (see
    confirmation.deterministic_action_id) rather than minted randomly.
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
        # executed, and nothing was ever attempted against the real
        # mutating tool to find this out.
        record: ToolCallRecord = {
            "callId": str(uuid.uuid4()),
            "toolName": tool_name,
            "argsSummary": tool_args,
            "resultSummary": None,
            "isSensitive": True,
            "startedAt": now_iso(),
            "finishedAt": now_iso(),
            "error": validation_error,
        }
        state["toolCallLog"] = state.get("toolCallLog", []) + [record]
        state["_confirmationDryRunFailed"] = True
        state["pendingAction"] = None

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
        return {**state, "loopIteration": state.get("loopIteration", 0) + 1}

    state["_confirmationDryRunFailed"] = False

    action_id = confirmation.deterministic_action_id(
        state.get("threadId") or "local", state.get("loopIteration", 0), tool_name, tool_args
    )
    pending: PendingAction = confirmation.create_pending_action(
        action_id, action_type, state["activeCapability"], tool_args, eligibility_checked=True
    )
    state["pendingAction"] = pending

    mandatory_ui = build_mandatory_ui(action_type, "PENDING", {"preview": preview_result, "pending": pending})
    message = decision.get("message") or "Please review and confirm."

    interrupt_ui_state = {
        "uiMode": resolve_ui_mode(mandatory_ui),
        "assistantMessage": message,
        "canvasData": {**_build_canvas_data(state), "preview": preview_result},
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

    if isinstance(resumed, dict) and resumed.get("__confirmationReminder__"):
        # Free text arrived, but this is a CONFIRM_ACTION interrupt — never
        # treated as authorization. pendingAction is untouched; the
        # conditional edge re-interrupts with it unchanged.
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
        # produced solely by a real Confirm/Decline button click.
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
    # reminder rather than silently proceeding as if it were authorization.
    state["_confirmationReminder"] = True
    _emit(state, agentAction="CONFIRM_ACTION", interruptType="CONFIRM_ACTION", retryOrError="unexpected_resume_shape")
    return state


def _confirmed_action_message(action_type: str, exec_result: Dict[str, Any]) -> str:
    if action_type == "SUBMIT_CANCELLATION" and isinstance(exec_result, dict) and not exec_result.get("error"):
        order_number = exec_result.get("orderNumber", "your order")
        resulting_status = exec_result.get("resultingOrderStatus", "cancelled")
        return f"Done — {order_number} has been submitted for cancellation. Status: {resulting_status}."

    if action_type == "CREATE_RETURN" and isinstance(exec_result, dict) and not exec_result.get("error"):
        order_number = exec_result.get("orderNumber", "your order")
        refund_estimate = exec_result.get("refundEstimate")
        refund_text = f" Estimated refund: ${refund_estimate:.2f}." if refund_estimate is not None else ""
        return f"Done — your return for {order_number} has been submitted.{refund_text}"

    return "Your request has been submitted."


def execute_confirmed_action_node(state: AgentStateV3) -> AgentStateV3:
    """
    Reached only after request_confirmation resumes with a real
    {"confirmation": {...}} payload. Runs all seven validate_confirmation
    checks before anything executes; an idempotency replay returns the
    already-recorded result instead of re-executing; every other rejection
    reason clears the stale pendingAction and hands back to agent_reason
    rather than silently retrying.
    """

    confirmation_reply = state.get("_confirmationReply") or {}
    pending = state.get("pendingAction")
    result = confirmation.validate_confirmation(pending, confirmation_reply)
    state["_confirmationReply"] = None

    if not result.ok:
        if result.reason == "IDEMPOTENCY_REPLAY" and pending:
            cached_result = idempotency.get_recorded_result(pending["actionId"])
            mandatory_ui = build_mandatory_ui(pending["actionType"], "CONFIRMED", {"result": cached_result})
            state["_mandatoryUi"] = mandatory_ui
            decision = {
                "action": "FINISH",
                "message": "This was already submitted — here's the confirmation.",
                "toolName": None,
                "toolArgs": {},
                "uiProposal": [],
            }
            state["_decision"] = decision
            state["_confirmationInvalid"] = None
            _emit(
                state,
                agentAction="REPLAY_SHORT_CIRCUITED",
                interactionType="CONFIRM_ACTION",
                interactionSource="A2UI",
                confirmationActionId=pending["actionId"],
                retryOrError="idempotency_replay_returned_cached_result",
                finalOutcome="FINAL",
            )
            return {**state, "messages": _messages_for_decision(decision)}

        # Any other rejection: never execute, never silently retry. Clear
        # the stale pendingAction and hand back to agent_reason.
        state["pendingAction"] = None
        state["_confirmationInvalid"] = result.reason
        _emit(
            state,
            agentAction="CONFIRM_ACTION",
            interactionType="CONFIRM_ACTION",
            interactionSource="A2UI",
            retryOrError=f"confirmation_rejected:{result.reason}",
        )
        return state

    state["_confirmationInvalid"] = None

    if not result.accepted:
        # Declined: consumed, never executed — control returns to
        # agent_reason to respond conversationally rather than through a
        # mandatory completion screen (declining isn't a transactional
        # completion state). agent_reason's own mandatory decline gate
        # (see agent_reason_node) is what turns this into the customer-
        # facing "no problem" reply, never the LLM's own judgment.
        pending["consumed"] = True
        state["pendingAction"] = None
        state["_confirmationDeclined"] = True
        _emit(
            state,
            agentAction="CONFIRM_ACTION",
            interactionType="CONFIRM_ACTION",
            interactionSource="A2UI",
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
    except Exception as exc:  # noqa: BLE001 - surfaced via toolCallLog, not swallowed
        exec_result = {"error": str(exc)}
        exec_error = str(exc)

    record: ToolCallRecord = {
        "callId": str(uuid.uuid4()),
        "toolName": tool_name,
        "argsSummary": pending["proposedPayload"],
        "resultSummary": exec_result,
        "isSensitive": True,
        "startedAt": now_iso(),
        "finishedAt": now_iso(),
        "error": exec_error,
    }

    pending["consumed"] = True
    pending["executed"] = True
    state["pendingAction"] = pending
    idempotency.record_executed(pending["actionId"], exec_result)

    mandatory_ui = build_mandatory_ui(pending["actionType"], "CONFIRMED", {"result": exec_result})
    state["_mandatoryUi"] = mandatory_ui
    decision = {
        "action": "FINISH",
        "message": _confirmed_action_message(pending["actionType"], exec_result),
        "toolName": None,
        "toolArgs": {},
        "uiProposal": [],
    }
    state["_decision"] = decision

    _emit(
        state,
        agentAction="EXECUTE_SENSITIVE_ACTION",
        interactionType="CONFIRM_ACTION",
        interactionSource="A2UI",
        requestedTool=tool_name,
        toolResultSummary=exec_result,
        confirmationActionId=pending["actionId"],
        latencyMs=stopwatch.elapsed_ms(),
        finalOutcome="FINAL",
    )

    return {
        **state,
        "toolCallLog": state.get("toolCallLog", []) + [record],
        "messages": _messages_for_decision(decision),
    }


def escalate_node(state: AgentStateV3) -> AgentStateV3:
    if not state.get("_escalationReason"):
        loop_safety.escalate(state, "max_iterations")
    return state


def finish_node(state: AgentStateV3) -> AgentStateV3:
    decision = state.get("_decision", {})
    message = decision.get("message") or "Here's what I found."
    active_capability = state.get("activeCapability")

    mandatory_ui = state.get("_mandatoryUi")

    if mandatory_ui is not None:
        # Code-owned transactional/completion UI — never passed through
        # validate_components. The agent's own uiProposal (if any) is
        # never even read on this path, by construction.
        components = mandatory_ui
        origin = "MANDATORY_DETERMINISTIC"
    elif active_capability in CAPABILITIES:
        capability = get_capability(active_capability)
        components, origin = validate_components(
            decision.get("uiProposal"), capability, state.get("toolCallLog", [])
        )
    else:
        components, origin = [{"type": WELCOME, "props": {}, "dataKey": None}], "DETERMINISTIC_FALLBACK"

    state["a2uiComponents"] = components
    state["a2uiOrigin"] = origin
    state["uiState"] = {
        "uiMode": resolve_ui_mode(components),
        "assistantMessage": message,
        "canvasData": _build_canvas_data(state),
        "a2ui": components,
    }
    state["_mandatoryUi"] = None
    # escalate() already sets status="ERROR" before this node runs — don't
    # clobber it back to "FINAL" if that happened.
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


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_agent_reason(state: AgentStateV3) -> str:
    if loop_safety.iteration_budget_exceeded(state):
        return "escalate"

    decision = state.get("_decision", {})
    action = decision.get("action")

    if action == "CALL_TOOL":
        capability = get_capability(state["activeCapability"])
        if decision.get("toolName") in capability.sensitive_tool_names:
            # Decided on the EDGE, before execute_tool ever runs — a
            # sensitive tool call always goes through confirmation, never
            # straight to execution.
            return "request_confirmation"
        return "execute_tool"
    if action == "ASK_CUSTOMER":
        return "ask_customer"
    return "finish"


def route_after_execute_tool(state: AgentStateV3) -> str:
    if state.get("status") == "ERROR":
        return "finish"
    return "agent_reason"


def route_after_ask_customer(state: AgentStateV3) -> str:
    if state.get("_reAsk"):
        return "ask_customer"
    return "agent_reason"


def route_after_request_confirmation(state: AgentStateV3) -> str:
    if state.get("status") == "ERROR":
        return "finish"
    if state.get("_confirmationDryRunFailed"):
        return "agent_reason"
    if state.get("_confirmationReminder"):
        return "request_confirmation"
    return "execute_confirmed_action"


def route_after_execute_confirmed_action(state: AgentStateV3) -> str:
    if state.get("_confirmationInvalid"):
        return "agent_reason"
    if state.get("_confirmationDeclined"):
        return "agent_reason"
    return "finish"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentStateV3)
    graph.add_node("classify_capability", classify_capability_node)
    graph.add_node("enforce_capability_switch", enforce_capability_switch_node)
    graph.add_node("agent_reason", agent_reason_node)
    graph.add_node("execute_tool", execute_tool_node)
    graph.add_node("ask_customer", ask_customer_node)
    graph.add_node("request_confirmation", request_confirmation_node)
    graph.add_node("execute_confirmed_action", execute_confirmed_action_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("finish", finish_node)

    graph.set_entry_point("classify_capability")
    graph.add_edge("classify_capability", "enforce_capability_switch")
    graph.add_edge("enforce_capability_switch", "agent_reason")
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
        "execute_tool", route_after_execute_tool, {"agent_reason": "agent_reason", "finish": "finish"}
    )
    graph.add_conditional_edges(
        "ask_customer", route_after_ask_customer, {"ask_customer": "ask_customer", "agent_reason": "agent_reason"}
    )
    graph.add_conditional_edges(
        "request_confirmation",
        route_after_request_confirmation,
        {
            "agent_reason": "agent_reason",
            "request_confirmation": "request_confirmation",
            "execute_confirmed_action": "execute_confirmed_action",
            "finish": "finish",
        },
    )
    graph.add_conditional_edges(
        "execute_confirmed_action",
        route_after_execute_confirmed_action,
        {"agent_reason": "agent_reason", "finish": "finish"},
    )
    graph.add_edge("escalate", "finish")
    graph.add_edge("finish", END)

    return graph


v3_agent_graph = build_graph().compile(checkpointer=get_checkpointer())
