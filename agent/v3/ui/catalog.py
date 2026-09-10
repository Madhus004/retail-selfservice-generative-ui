# agent/v3/ui/catalog.py
#
# V3's generative-UI catalog — fine-grained, composable primitives instead
# of V2's whole-screen fixed types (agreed explicitly: the LLM never emits
# free-form HTML/JSX, it only ever picks *and orders* small validated
# pieces). Reuses agent/shared/a2ui_types.py's allow-list-filter/fallback
# pattern directly (same "LLM proposes, code disposes" discipline V1/V2
# already established) and adds one thing V2's catalog didn't have: a
# dataKey existence check against toolCallLog, so a proposed component can
# never reference data nothing actually fetched.
#
# One assistant turn = an ordered list of these, not one fixed screen id.
# A handful of types are "primary" (screen-anchoring — decide uiMode for
# the frontend) and the rest are supplemental (rendered alongside).

from typing import Any, Dict, List, Optional, Tuple

from shared.a2ui_types import filter_to_allowlist

from v3.capabilities.types import Capability
from v3.state import ToolCallRecord

# --- ORDER_STATUS's starting slice. Grows one capability at a time. ---

STATUS_PILL = "StatusPill"
TRACKING_TIMELINE = "TrackingTimeline"
DELIVERY_PROOF_CARD = "DeliveryProofCard"
SERVICE_RECOVERY_BANNER = "ServiceRecoveryBanner"
ORDER_SUMMARY_CARD = "OrderSummaryCard"
ORDER_LIST_PICKER = "OrderListPicker"
SUGGESTED_ACTIONS = "SuggestedActions"
WELCOME = "Welcome"

# Phase 3 (CANCELLATION) — the first sensitive-action capability.
# CANCELLATION_ORDER_PICKER/CANCELLATION_ITEM_PICKER are LLM-proposable
# (allowed_ui_components); CONFIRMATION_CARD is always code-owned (see
# build_mandatory_ui below) — never influenced by an LLM proposal, by
# construction, the same discipline V2's a2ui.py established.
CANCELLATION_ORDER_PICKER = "CancellationOrderPicker"
CANCELLATION_ITEM_PICKER = "CancellationItemPicker"
CONFIRMATION_CARD = "ConfirmationCard"

# Phase 4 (RETURNS) — reuses ORDER_LIST_PICKER for order selection (a
# return-eligible order list is shaped identically to any other order
# list) and CONFIRMATION_CARD for its mandatory propose/confirm screens
# (already phase/payload-generic); only the item/reason/method asks need
# new, RETURNS-specific primitives.
RETURN_ITEM_PICKER = "ReturnItemPicker"
RETURN_REASON_PROMPT = "ReturnReasonPrompt"
RETURN_METHOD_PROMPT = "ReturnMethodPrompt"

ALL_COMPONENT_TYPES = {
    STATUS_PILL,
    TRACKING_TIMELINE,
    DELIVERY_PROOF_CARD,
    SERVICE_RECOVERY_BANNER,
    ORDER_SUMMARY_CARD,
    ORDER_LIST_PICKER,
    SUGGESTED_ACTIONS,
    WELCOME,
    CANCELLATION_ORDER_PICKER,
    CANCELLATION_ITEM_PICKER,
    CONFIRMATION_CARD,
    RETURN_ITEM_PICKER,
    RETURN_REASON_PROMPT,
    RETURN_METHOD_PROMPT,
}

# Screen-anchoring types — one of these (or WELCOME, the universal
# fallback) determines the frontend's uiMode. Everything else is
# supplemental and renders alongside whichever primary is present.
PRIMARY_COMPONENT_TYPES = {
    ORDER_SUMMARY_CARD,
    ORDER_LIST_PICKER,
    WELCOME,
    CANCELLATION_ORDER_PICKER,
    CANCELLATION_ITEM_PICKER,
    CONFIRMATION_CARD,
    RETURN_ITEM_PICKER,
    RETURN_REASON_PROMPT,
    RETURN_METHOD_PROMPT,
}

# actionType (PendingAction) + phase -> the mandatory, code-owned
# component type. Never influenced by an LLM proposal — see
# build_mandatory_ui below, called only from graph.py's
# request_confirmation_node/execute_confirmed_action_node.
_MANDATORY_UI_TYPES = {
    ("SUBMIT_CANCELLATION", "PENDING"): CONFIRMATION_CARD,
    ("SUBMIT_CANCELLATION", "CONFIRMED"): CONFIRMATION_CARD,
    ("CREATE_RETURN", "PENDING"): CONFIRMATION_CARD,
    ("CREATE_RETURN", "CONFIRMED"): CONFIRMATION_CARD,
}


def _latest_tool_call_id(tool_call_log: List[ToolCallRecord], tool_name: str) -> bool:
    return any(
        record["toolName"] == tool_name and not record.get("error") for record in tool_call_log
    )


def _drop_components_with_missing_data(
    components: List[Dict[str, Any]], tool_call_log: List[ToolCallRecord]
) -> List[Dict[str, Any]]:
    """
    A component referencing a dataKey that nothing in this turn's
    toolCallLog actually produced is dropped before it ever reaches the
    frontend — the fine-grained-catalog equivalent of V2's dataKey
    convention, now checked against the ordered log instead of assumed.
    """

    kept = []

    for component in components:
        data_key = component.get("dataKey")

        if data_key is None or _latest_tool_call_id(tool_call_log, data_key):
            kept.append(component)

    return kept


def build_deterministic_fallback(
    capability: Capability, tool_call_log: List[ToolCallRecord]
) -> List[Dict[str, Any]]:
    if capability.name == "ORDER_STATUS":
        if _latest_tool_call_id(tool_call_log, "get_order_status_tool"):
            return [{"type": ORDER_SUMMARY_CARD, "props": {}, "dataKey": "get_order_status_tool"}]
        if _latest_tool_call_id(tool_call_log, "get_recent_orders_tool"):
            return [{"type": ORDER_LIST_PICKER, "props": {}, "dataKey": "get_recent_orders_tool"}]

    if capability.name == "CANCELLATION":
        return [
            {
                "type": CANCELLATION_ORDER_PICKER,
                "props": {},
                "dataKey": "get_cancellation_eligible_orders_tool",
            }
        ]

    if capability.name == "RETURNS":
        if _latest_tool_call_id(tool_call_log, "get_return_eligible_items_tool"):
            return [
                {"type": RETURN_ITEM_PICKER, "props": {}, "dataKey": "get_return_eligible_items_tool"}
            ]
        return [
            {"type": ORDER_LIST_PICKER, "props": {}, "dataKey": "get_return_eligible_orders_tool"}
        ]

    return [{"type": WELCOME, "props": {}, "dataKey": None}]


def build_mandatory_ui(action_type: str, phase: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Code-owned transactional/completion UI — called only from graph.py's
    request_confirmation_node/execute_confirmed_action_node, never passed
    through validate_components. The agent's own uiProposal is never even
    read on this path, by construction, not by convention.
    """

    component_type = _MANDATORY_UI_TYPES.get((action_type, phase), WELCOME)
    return [{"type": component_type, "props": {**payload, "phase": phase}, "dataKey": None}]


def validate_components(
    proposal: Optional[List[Dict[str, Any]]],
    capability: Capability,
    tool_call_log: List[ToolCallRecord],
) -> Tuple[List[Dict[str, Any]], str]:
    fallback = build_deterministic_fallback(capability, tool_call_log)
    allowed_types = set(capability.allowed_ui_components) & ALL_COMPONENT_TYPES

    type_filtered = filter_to_allowlist(proposal or [], allowed_types)
    data_filtered = _drop_components_with_missing_data(type_filtered, tool_call_log)

    if not data_filtered or not any(c["type"] in PRIMARY_COMPONENT_TYPES for c in data_filtered):
        return fallback, "DETERMINISTIC_FALLBACK"

    return data_filtered, "AGENT_PROPOSED"


def resolve_ui_mode(components: List[Dict[str, Any]]) -> str:
    for component in components:
        if component["type"] in PRIMARY_COMPONENT_TYPES:
            return component["type"]
    return WELCOME
