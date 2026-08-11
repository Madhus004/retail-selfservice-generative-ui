import uuid
from pathlib import Path

from fastapi import HTTPException

from data.mock_orders import MOCK_CUSTOMER, MOCK_ORDERS


def get_recent_orders():
    recent_orders = []

    for order_bundle in MOCK_ORDERS.values():
        order = order_bundle["order"]
        order_lines = order_bundle["orderLines"]
        packages = order_bundle["packages"]
        delivery_promises = order_bundle["deliveryPromises"]

        promise_results = [promise["promiseResult"] for promise in delivery_promises]

        if "missed" in promise_results:
            promise_status_label = "Missed"
        elif "at_risk" in promise_results:
            promise_status_label = "At risk"
        elif promise_results:
            promise_status_label = "Met"
        else:
            # Not yet shipped — nothing has been promised or missed yet.
            promise_status_label = "Processing"

        recent_orders.append(
            {
                "orderNumber": order["orderNumber"],
                "customerId": order["customerId"],
                "customerName": MOCK_CUSTOMER["name"],
                "orderDate": order["orderDate"],
                "orderStatus": order["orderStatus"],
                "orderTotal": order["orderTotal"],
                "currency": order["currency"],
                "itemCount": sum(line["quantity"] for line in order_lines),
                "packageCount": len(packages),
                "summary": ", ".join(line["itemName"] for line in order_lines),
                "originalPromiseDate": order["originalPromiseDate"],
                "promisedDelivery": promise_status_label,
            }
        )

    return {
        "customer": MOCK_CUSTOMER,
        "orders": recent_orders,
    }


def get_order_promise_dashboard(order_number: str):
    order_bundle = MOCK_ORDERS.get(order_number)

    if not order_bundle:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_number} was not found.",
        )

    order = order_bundle["order"]
    order_lines = order_bundle["orderLines"]
    packages = order_bundle["packages"]
    package_lines = order_bundle["packageLines"]
    tracking_events = order_bundle["trackingEvents"]
    delivery_promises = order_bundle["deliveryPromises"]
    delivery_proofs = order_bundle["deliveryProofs"]
    service_recovery_actions = order_bundle["serviceRecoveryActions"]

    promise_results = [promise["promiseResult"] for promise in delivery_promises]

    if "missed" in promise_results:
        overall_promise_status = "Missed"
        customer_summary = (
            "We’re sorry your order arrived later than promised. "
            "We’ve applied the available service recovery for this delay."
        )
    elif "at_risk" in promise_results:
        overall_promise_status = "At risk"
        customer_summary = (
            "Your package is delayed due to weather and may arrive after the original promise date. "
            "We’ll keep watching the latest carrier updates."
        )
    else:
        overall_promise_status = "Met"
        customer_summary = "Good news — your order was delivered before the promised date."

    order_lines_by_id = {line["orderLineId"]: line for line in order_lines}

    tracking_events_by_package = {}
    for event in tracking_events:
        tracking_events_by_package.setdefault(event["packageId"], []).append(event)

    promises_by_package = {
        promise["packageId"]: promise for promise in delivery_promises
    }

    proofs_by_package = {
        proof["packageId"]: proof for proof in delivery_proofs
    }

    service_actions_by_package = {}
    for action in service_recovery_actions:
        package_id = action.get("packageId") or "order"
        service_actions_by_package.setdefault(package_id, []).append(action)

    dashboard_packages = []

    for package in packages:
        package_id = package["packageId"]

        package_item_links = [
            package_line
            for package_line in package_lines
            if package_line["packageId"] == package_id
        ]

        package_items = []
        for package_line in package_item_links:
            order_line = order_lines_by_id[package_line["orderLineId"]]
            package_items.append(
                {
                    **order_line,
                    "packageQuantity": package_line["quantity"],
                }
            )

        promise = promises_by_package.get(package_id)
        proof = proofs_by_package.get(package_id)
        package_service_actions = service_actions_by_package.get(package_id, [])

        dashboard_packages.append(
            {
                **package,
                "items": package_items,
                "trackingEvents": tracking_events_by_package.get(package_id, []),
                "promise": promise,
                "deliveryProof": proof,
                "serviceRecoveryActions": package_service_actions,
            }
        )

    return {
        "customer": MOCK_CUSTOMER,
        "order": order,
        "summary": {
            "customerMessage": customer_summary,
            "overallPromiseStatus": overall_promise_status,
            "packageCount": len(packages),
            "itemCount": sum(line["quantity"] for line in order_lines),
            "hasDeliveryProof": len(delivery_proofs) > 0,
            "hasServiceRecovery": len(service_recovery_actions) > 0,
        },
        "packages": dashboard_packages,
        "serviceRecoveryActions": service_recovery_actions,
    }


POLICY_DIR = Path(__file__).parent / "data" / "policies"


def read_policy_file(file_name: str) -> str:
    policy_path = POLICY_DIR / file_name

    if not policy_path.exists():
        return ""

    return policy_path.read_text(encoding="utf-8")


def retrieve_policy_context(
    promise_result: str | None = None,
    reason_code: str | None = None,
    issue_type: str | None = None,
) -> dict:
    """
    Simple local policy retrieval.

    This is our first RAG-style layer:
    - It retrieves policy text from markdown docs.
    - Later we can replace this with vector search.
    """

    selected_files = []

    if issue_type == "wrong_delivery":
        selected_files.append("wrong_delivery_claim_policy.md")

    if issue_type == "cancel_order":
        selected_files.append("order_cancellation_policy.md")

    if promise_result in {"met", "missed", "at_risk"}:
        selected_files.append("delivery_promise_policy.md")
        selected_files.append("service_recovery_policy.md")

    if reason_code in {"carrier_delay", "weather_delay"}:
        selected_files.append("service_recovery_policy.md")

    if not selected_files:
        selected_files = [
            "delivery_promise_policy.md",
            "service_recovery_policy.md",
        ]

    # Remove duplicates while preserving order.
    unique_files = list(dict.fromkeys(selected_files))

    policies = []

    for file_name in unique_files:
        content = read_policy_file(file_name)

        if content:
            policies.append(
                {
                    "fileName": file_name,
                    "content": content,
                }
            )

    return {
        "retrievedPolicyFiles": unique_files,
        "policyContext": "\n\n---\n\n".join(
            policy["content"] for policy in policies
        ),
    }


def get_cancellation_eligible_orders():
    """
    Orders can only be cancelled before they ship. Eligibility is read from
    each order's "cancellation" flag rather than re-derived here, so a
    future order can be marked eligible/ineligible without touching this
    function.
    """

    eligible_orders = []

    for order_bundle in MOCK_ORDERS.values():
        cancellation = order_bundle.get("cancellation") or {}

        if not cancellation.get("eligible"):
            continue

        order = order_bundle["order"]

        items = [
            {
                "orderLineId": line["orderLineId"],
                "itemName": line["itemName"],
                "color": line["color"],
                "size": line["size"],
                "price": line["price"],
                "quantity": line["quantity"],
                "cancellableQuantity": line["quantity"]
                - line.get("cancelledQuantity", 0),
            }
            for line in order_bundle["orderLines"]
        ]

        cancellable_items = [item for item in items if item["cancellableQuantity"] > 0]

        if not cancellable_items:
            continue

        eligible_orders.append(
            {
                "orderNumber": order["orderNumber"],
                "orderDate": order["orderDate"],
                "orderStatus": order["orderStatus"],
                "currency": order["currency"],
                "items": cancellable_items,
            }
        )

    return {
        "customer": MOCK_CUSTOMER,
        "orders": eligible_orders,
    }


def submit_order_cancellation(
    order_number: str,
    line_selections: list[dict],
    reason: str,
):
    """
    Server-side deterministic re-validation — the customer's selections are
    never trusted as-is, regardless of what the UI already prevented. Does
    not mutate MOCK_ORDERS: the response reflects what the cancellation
    would do, kept side-effect-free so this stays safe to call repeatedly
    (including from tests) without one call changing another's outcome.
    """

    order_bundle = MOCK_ORDERS.get(order_number)

    if not order_bundle:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_number} was not found.",
        )

    cancellation = order_bundle.get("cancellation") or {}

    if not cancellation.get("eligible"):
        raise HTTPException(
            status_code=409,
            detail=cancellation.get("reason")
            or f"Order {order_number} is no longer eligible for cancellation.",
        )

    if not line_selections:
        raise HTTPException(
            status_code=400,
            detail="Select at least one item to cancel.",
        )

    order_lines_by_id = {
        line["orderLineId"]: line for line in order_bundle["orderLines"]
    }

    cancelled_items = []

    for selection in line_selections:
        order_line_id = selection.get("orderLineId")
        requested_quantity = selection.get("quantity", 0)

        order_line = order_lines_by_id.get(order_line_id)

        if not order_line:
            raise HTTPException(
                status_code=400,
                detail=f"Order line {order_line_id} was not found on order {order_number}.",
            )

        cancellable_quantity = order_line["quantity"] - order_line.get(
            "cancelledQuantity", 0
        )

        if requested_quantity <= 0 or requested_quantity > cancellable_quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Requested cancellation quantity for {order_line['itemName']} "
                    f"exceeds the {cancellable_quantity} unit(s) available to cancel."
                ),
            )

        cancelled_items.append(
            {
                "itemName": order_line["itemName"],
                "color": order_line["color"],
                "size": order_line["size"],
                "quantity": requested_quantity,
            }
        )

    total_cancellable_units = sum(
        line["quantity"] - line.get("cancelledQuantity", 0)
        for line in order_bundle["orderLines"]
    )
    total_requested_units = sum(item["quantity"] for item in cancelled_items)

    resulting_order_status = (
        "Cancelled"
        if total_requested_units >= total_cancellable_units
        else "Partially cancelled"
    )

    return {
        "cancellationId": f"CANC-{order_number.replace('-', '')}-{uuid.uuid4().hex[:6].upper()}",
        "orderNumber": order_number,
        "status": "submitted",
        "cancelledItems": cancelled_items,
        "reason": reason,
        "resultingOrderStatus": resulting_order_status,
    }