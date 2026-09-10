# agent/v2/tools/wrong_delivery_tools.py
#
# submit_wrong_delivery_claim is genuinely NEW — unlike CANCELLATION's
# tools, there is no V1 function to import here. V1 declared a
# SUBMIT_WRONG_DELIVERY_CLAIM intent but never actually wired claim
# submission server-side (confirmed: the frontend's
# AssistantProvider.submitWrongDeliveryClaim is a client-only stub that
# fabricates a fake claim id and never calls the backend at all). Because
# this logic has no V1 counterpart, it lives entirely in agent/v2/ rather
# than being added to agent/tools.py — agent/tools.py stays on the
# untouched-V1-files list (plan section 4) even though this capability
# exists.
#
# Reuses the shared mock data directly (agent/data/mock_orders.py, plan
# section 5) — the same MOCK_ORDERS dict V1's tools.py itself reads from.

import uuid

from fastapi import HTTPException
from langchain_core.tools import tool

from data.mock_orders import MOCK_ORDERS


def build_wrong_delivery_claim_preview(order_number: str, description: str) -> dict:
    """
    ALL of submit_wrong_delivery_claim's validation (404/409/400) —
    deliberately factored out from claimId/status generation (2026-08
    premature-execution fix). Mutates nothing, safe to call any number of
    times per request_confirmation_node resume (LangGraph's interrupt()
    semantics re-executes everything before interrupt() on every resume)
    without ever generating a transaction id or claiming "status":
    "submitted" — that only ever happens once, inside
    submit_wrong_delivery_claim itself, called only by
    execute_confirmed_action_node after a valid Confirm.
    """

    order_bundle = MOCK_ORDERS.get(order_number)

    if not order_bundle:
        raise HTTPException(status_code=404, detail=f"Order {order_number} was not found.")

    delivery_promises = order_bundle.get("deliveryPromises") or []
    delivered = any(promise.get("actualDeliveredAt") for promise in delivery_promises)

    if not delivered:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Order {order_number} hasn't been marked as delivered yet, "
                "so a wrong-delivery claim can't be filed against it."
            ),
        )

    if not description or not description.strip():
        raise HTTPException(
            status_code=400,
            detail="Please describe what happened so we can review the claim.",
        )

    return {"orderNumber": order_number, "description": description}


def submit_wrong_delivery_claim(order_number: str, description: str) -> dict:
    """
    The REAL execution — only ever called once, from
    execute_confirmed_action_node, after a valid structured Confirm
    (2026-08 premature-execution fix).
    """

    build_wrong_delivery_claim_preview(order_number, description)

    claim_id = f"CLAIM-{order_number.replace('-', '')}-{uuid.uuid4().hex[:6].upper()}"

    return {
        "claimId": claim_id,
        "orderNumber": order_number,
        "status": "submitted",
        "slaMessage": "We'll review this and follow up within 1-2 business days.",
    }


@tool
def submit_wrong_delivery_claim_tool(order_number: str, description: str) -> dict:
    """Submit a wrong-delivery claim for an order that tracking shows as
    delivered but the customer says they didn't receive, or that went to
    the wrong address. description should summarize what the customer
    reported. This is a sensitive action: it will always be shown to the
    customer for confirmation before anything is actually submitted, so
    call it as soon as you have enough information — you do not need to
    ask a separate yes/no question first."""

    return submit_wrong_delivery_claim(order_number, description)
