# agent/v2/tools/cancellation_tools.py
#
# Thin @tool wrappers around agent/tools.py's existing, already-tested
# cancellation functions — imported directly, never forked (plan section
# 5). submit_order_cancellation_tool is sensitive: the graph never lets
# execute_tool call it directly (see graph.py's sensitive-tool routing at
# agent_reason and the defense-in-depth rejection inside execute_tool
# itself), and — as of the 2026-08 premature-execution fix — never runs
# during the PENDING/preview phase either. Only execute_confirmed_action_node
# calls it, exactly once, after a valid structured Confirm.

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from langchain_core.tools import tool

from tools import get_cancellation_eligible_orders, submit_order_cancellation


def validate_cancellation_proposal(
    order_number: str,
    line_selections: List[dict],
    reason: str,
    eligible_orders_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Validates a proposed cancellation against an ALREADY-FETCHED
    get_cancellation_eligible_orders_tool result — never calls
    tools.submit_order_cancellation (V1, protected — this project's
    baseline stays byte-for-byte unchanged). This is what
    request_confirmation_node calls for the PENDING/preview stage instead
    of invoking the real, ID-minting, "status": "submitted"-returning V1
    function: the eligibility DATA it validates against was itself already
    produced by tools.get_cancellation_eligible_orders (reused directly,
    not forked), so this doesn't reimplement V1's eligibility rules —
    it only checks the customer's requested selection against numbers V1
    already computed and handed us. Raises HTTPException with the same
    404/400 status codes submit_order_cancellation itself would raise, for
    a consistent customer-facing error shape either way. Returns a preview
    dict with NO cancellationId and NO "status" field — nothing here can
    ever look like a completed submission, by construction, because
    nothing here ever calls the function that mints one.
    """

    orders = (eligible_orders_result or {}).get("orders") or []
    order = next((o for o in orders if o.get("orderNumber") == order_number), None)

    if not order:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_number} was not found or is not eligible to cancel.",
        )

    if not line_selections:
        raise HTTPException(status_code=400, detail="Select at least one item to cancel.")

    items_by_id = {item["orderLineId"]: item for item in order.get("items", [])}
    cancelled_items = []
    total_requested_units = 0

    for selection in line_selections:
        order_line_id = selection.get("orderLineId")
        requested_quantity = selection.get("quantity", 0)
        item = items_by_id.get(order_line_id)

        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"Order line {order_line_id} was not found on order {order_number}.",
            )

        if requested_quantity <= 0 or requested_quantity > item.get("cancellableQuantity", 0):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Requested cancellation quantity for {item['itemName']} exceeds the "
                    f"{item.get('cancellableQuantity', 0)} unit(s) available to cancel."
                ),
            )

        cancelled_items.append(
            {
                "itemName": item["itemName"],
                "color": item["color"],
                "size": item["size"],
                "quantity": requested_quantity,
            }
        )
        total_requested_units += requested_quantity

    total_cancellable_units = sum(i.get("cancellableQuantity", 0) for i in order.get("items", []))
    resulting_order_status = (
        "Cancelled" if total_requested_units >= total_cancellable_units else "Partially cancelled"
    )

    return {
        "orderNumber": order_number,
        "cancelledItems": cancelled_items,
        "reason": reason,
        "resultingOrderStatus": resulting_order_status,
    }


@tool
def get_cancellation_eligible_orders_tool() -> dict:
    """List the customer's orders that are still eligible for cancellation
    (not yet shipped), with cancellable items and quantities per order."""

    return get_cancellation_eligible_orders()


@tool
def submit_order_cancellation_tool(order_number: str, line_selections: List[dict], reason: str) -> dict:
    """Submit a cancellation for specific items/quantities on an order.
    line_selections is a list of {orderLineId, quantity} pairs — only
    include lines the customer actually wants cancelled, at the exact
    quantities from get_cancellation_eligible_orders_tool's cancellable
    amounts. This is a sensitive action: it will always be shown to the
    customer for confirmation before anything is actually submitted, so
    call it as soon as you know exactly what to cancel — you do not need
    to ask for a separate yes/no first."""

    return submit_order_cancellation(order_number, line_selections, reason)
