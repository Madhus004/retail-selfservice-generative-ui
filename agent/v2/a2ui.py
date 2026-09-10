# agent/v2/a2ui.py
#
# Hybrid A2UI ownership (plan section 22-25). validate_agent_a2ui (Phase 1)
# is the informational-UI half: the agent may propose a component from its
# capability's allow-list; anything outside that list, or an empty
# proposal, deterministically falls back — the same "LLM proposes, code
# disposes" discipline V1's validate_a2ui_components already applies,
# reused via the shared helper rather than duplicated.
#
# build_mandatory_ui (Phase 4) is the other half: every transactional/
# confirmation/completion state is built here, directly, by
# request_confirmation_node and execute_confirmed_action_node — these code
# paths never read state["a2uiProposal"]/decision["uiProposal"] at all, so
# there is no way for an LLM proposal to reach a confirmation/completion
# screen, by construction, not by convention (plan section 22).

from typing import Any, Dict, List, Tuple

from shared.a2ui_types import validate_or_fallback
from v2.capabilities.types import Capability


def build_deterministic_fallback(
    capability: Capability, tool_results: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if capability.name == "ORDER_STATUS":
        if "get_order_status_tool" in tool_results:
            return [
                {"type": "orderStatus", "props": {}, "dataKey": "get_order_status_tool"}
            ]
        return [
            {"type": "orderSelection", "props": {}, "dataKey": "get_recent_orders_tool"}
        ]

    if capability.name == "CANCELLATION":
        return [
            {
                "type": "cancellationOrderSelection",
                "props": {},
                "dataKey": "get_cancellation_eligible_orders_tool",
            }
        ]

    if capability.name == "WRONG_DELIVERY":
        if "get_order_status_tool" in tool_results:
            return [
                {"type": "wrongDeliveryClaimForm", "props": {}, "dataKey": "get_order_status_tool"}
            ]
        return [{"type": "welcome", "props": {}, "dataKey": None}]

    if capability.name == "RETURNS":
        if "get_return_eligible_items_tool" in tool_results:
            return [
                {"type": "returnItemSelection", "props": {}, "dataKey": "get_return_eligible_items_tool"}
            ]
        return [
            {"type": "orderSelection", "props": {}, "dataKey": "get_return_eligible_orders_tool"}
        ]

    return [{"type": "welcome", "props": {}, "dataKey": None}]


def validate_agent_a2ui(
    proposal: List[Dict[str, Any]],
    capability: Capability,
    tool_results: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], str]:
    fallback = build_deterministic_fallback(capability, tool_results)
    allowed_types = set(capability.allowed_agent_a2ui)

    return validate_or_fallback(proposal, allowed_types, fallback)


# actionType (PendingAction) + phase -> A2UI type. Phase 4 only wires the
# CANCELLATION entries; the RETURNS/WRONG_DELIVERY rows are declared now
# (matching the plan's full mandatory-UI list, section 24) so Phase 5-6 add
# capabilities without touching this table's shape, only new rows.
_MANDATORY_UI_TYPES = {
    ("SUBMIT_CANCELLATION", "PENDING"): "cancellationConfirmationPending",
    ("SUBMIT_CANCELLATION", "CONFIRMED"): "cancellationConfirmed",
    ("CREATE_RETURN", "PENDING"): "returnConfirmationPending",
    ("CREATE_RETURN", "CONFIRMED"): "returnSubmitted",
    ("SUBMIT_WRONG_DELIVERY_CLAIM", "PENDING"): "claimConfirmationPending",
    ("SUBMIT_WRONG_DELIVERY_CLAIM", "CONFIRMED"): "claimSubmitted",
}


def build_mandatory_ui(action_type: str, phase: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    component_type = _MANDATORY_UI_TYPES.get((action_type, phase), "welcome")

    return [{"type": component_type, "props": payload, "dataKey": None}]
