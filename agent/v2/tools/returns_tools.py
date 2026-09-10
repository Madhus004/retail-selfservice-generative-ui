# agent/v2/tools/returns_tools.py
#
# Genuinely new deterministic functions — no V1 equivalent exists (V1 has
# no returns concept at all beyond one sentence of policy guidance).
# Modeled on tools.submit_order_cancellation's validation shape
# (404/409/400, side-effect-free) but is new code rather than a shared
# function: return eligibility (post-delivery, within a window) and
# cancellation eligibility (pre-shipment) are different business rules
# that shouldn't be conflated into one function (plan section 9).
#
# Reuses the shared mock order data directly (agent/data/mock_orders.py)
# for item details, plus the new, V2-only agent/data/mock_returns.py for
# eligibility — both read-only, nothing here mutates either.

import uuid
from typing import Any, Dict, List

from fastapi import HTTPException
from langchain_core.tools import tool

from data.mock_orders import MOCK_CUSTOMER, MOCK_ORDERS
from data.mock_returns import MOCK_RETURNS


def get_return_eligible_orders() -> Dict[str, Any]:
    """
    Mirrors tools.get_cancellation_eligible_orders' shape exactly (plan
    section 5's sharing precedent) but for returns: every order the
    customer could plausibly pick from at the RETURNS order-selection
    stage, pre-filtered to only ones MOCK_RETURNS marks eligible. Added
    2026-08 (structured-interaction fix) specifically so the order-
    selection screen doesn't offer orders that are still in transit or not
    yet shipped — RETURNS previously reused get_recent_orders_tool for
    this, which returns every order regardless of return eligibility.
    """

    eligible_orders = []

    for order_bundle in MOCK_ORDERS.values():
        order = order_bundle["order"]
        returns_bundle = MOCK_RETURNS.get(order["orderNumber"])

        if not returns_bundle or not returns_bundle.get("eligible"):
            continue

        eligible_orders.append(
            {
                "orderNumber": order["orderNumber"],
                "orderDate": order["orderDate"],
                "orderStatus": order["orderStatus"],
                "currency": order["currency"],
                "items": returns_bundle["items"],
            }
        )

    return {
        "customer": MOCK_CUSTOMER,
        "orders": eligible_orders,
    }


def get_return_eligible_items(order_number: str) -> Dict[str, Any]:
    order_bundle = MOCK_ORDERS.get(order_number)

    if not order_bundle:
        raise HTTPException(status_code=404, detail=f"Order {order_number} was not found.")

    returns_bundle = MOCK_RETURNS.get(order_number) or {
        "eligible": False,
        "reason": f"Order {order_number} is not eligible for a return.",
        "returnWindowExpiresAt": None,
        "returnMethods": [],
        "items": [],
    }

    return {
        "orderNumber": order_number,
        "eligible": returns_bundle["eligible"],
        "reason": returns_bundle["reason"],
        "returnWindowExpiresAt": returns_bundle["returnWindowExpiresAt"],
        "returnMethods": returns_bundle["returnMethods"],
        "items": returns_bundle["items"],
    }


def build_return_preview(
    order_number: str,
    line_selections: List[dict],
    reason: str,
    method: str | None = None,
) -> Dict[str, Any]:
    """
    ALL of create_return's validation and computation (eligibility, item/
    quantity checks, refund estimate, method resolution) — deliberately
    factored out from ID/status generation (2026-08 premature-execution
    fix). Contains no randomness and mutates nothing, so it's trivially
    safe to call any number of times (including multiple times per
    request_confirmation_node resume, an unavoidable consequence of
    LangGraph's interrupt() semantics re-executing everything before the
    interrupt() call on every resume) without ever producing a different-
    looking "result" for the same input. request_confirmation_node calls
    this directly for the PENDING/preview stage; create_return below is
    the only thing that adds a returnId + "status": "submitted", and it's
    only ever called once, by execute_confirmed_action_node, after a
    valid Confirm.
    """

    order_bundle = MOCK_ORDERS.get(order_number)

    if not order_bundle:
        raise HTTPException(status_code=404, detail=f"Order {order_number} was not found.")

    returns_bundle = MOCK_RETURNS.get(order_number)

    if not returns_bundle or not returns_bundle.get("eligible"):
        detail = (returns_bundle or {}).get("reason") or f"Order {order_number} is not eligible for a return."
        raise HTTPException(status_code=409, detail=detail)

    if not line_selections:
        raise HTTPException(status_code=400, detail="Select at least one item to return.")

    items_by_id = {item["orderLineId"]: item for item in returns_bundle["items"]}
    returned_items = []
    refund_estimate = 0.0

    for selection in line_selections:
        order_line_id = selection.get("orderLineId")
        requested_quantity = selection.get("quantity", 0)

        item = items_by_id.get(order_line_id)

        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {order_line_id} was not found among order {order_number}'s returnable items.",
            )

        if requested_quantity <= 0 or requested_quantity > item["returnableQuantity"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Requested return quantity for {item['itemName']} exceeds the "
                    f"{item['returnableQuantity']} unit(s) available to return."
                ),
            )

        returned_items.append(
            {
                "itemName": item["itemName"],
                "color": item["color"],
                "size": item["size"],
                "quantity": requested_quantity,
            }
        )
        refund_estimate += item["price"] * requested_quantity

    available_methods = returns_bundle["returnMethods"]

    if method is not None:
        if method not in available_methods:
            raise HTTPException(
                status_code=400,
                detail=f"'{method}' is not an available return method for order {order_number}.",
            )
        return_method = method
    else:
        return_method = available_methods[0] if available_methods else "mail"

    return {
        "orderNumber": order_number,
        "returnedItems": returned_items,
        "reason": reason,
        "returnMethod": return_method,
        "refundEstimate": round(refund_estimate, 2),
    }


def create_return(
    order_number: str,
    line_selections: List[dict],
    reason: str,
    method: str | None = None,
) -> Dict[str, Any]:
    """
    The REAL execution — only ever called once, from
    execute_confirmed_action_node, after a valid structured Confirm
    (2026-08 premature-execution fix). Runs the exact same validation as
    the preview (via build_return_preview) and then, only here, mints the
    transaction id and marks it submitted — so a returnId/status:
    "submitted" can only ever exist as the result of a genuine, confirmed
    execution, never a proposal.
    """

    preview = build_return_preview(order_number, line_selections, reason, method)

    return {
        "returnId": f"RTN-{order_number.replace('-', '')}-{uuid.uuid4().hex[:6].upper()}",
        "status": "submitted",
        **preview,
    }


@tool
def get_return_eligible_orders_tool() -> dict:
    """List every order that's currently eligible for a return, with each
    order's returnable items and quantities. Use this when you don't yet
    know which order the customer means and there's more than one order to
    choose from — this only ever offers orders that are actually return-
    eligible, unlike get_recent_orders_tool which lists everything."""

    return get_return_eligible_orders()


@tool
def get_return_eligible_items_tool(order_number: str) -> dict:
    """Check whether an order is eligible for a return and, if so, list its
    returnable items with returnable quantities, the return window, and
    available return methods. This is the only source of truth for return
    eligibility, items, and quantities — never invent or assume any of
    them."""

    return get_return_eligible_items(order_number)


@tool
def create_return_tool(
    order_number: str,
    line_selections: List[dict],
    reason: str,
    method: str | None = None,
) -> dict:
    """Create a return for specific items/quantities on an order.
    line_selections is a list of {orderLineId, quantity} pairs — only
    include lines that actually appeared in
    get_return_eligible_items_tool's result for that order, at quantities
    no higher than their returnableQuantity. method, if given, must be one
    of that order's returnMethods (e.g. "mail" or "in_store") — omit it to
    use the default. This is a sensitive action: it will always be shown
    to the customer for confirmation before anything is actually
    submitted, so call it as soon as you know exactly what to return — you
    do not need to ask a separate yes/no question first."""

    return create_return(order_number, line_selections, reason, method)
