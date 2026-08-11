import json
import os
import re
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from state import AgentState
from tools import (
    get_cancellation_eligible_orders,
    get_order_promise_dashboard,
    get_recent_orders,
    retrieve_policy_context,
)

load_dotenv()


ALLOWED_A2UI_COMPONENTS = {
    "welcome",
    "orderSelection",
    "promiseDashboard",
    "deliveryProof",
    "serviceRecovery",
    "wrongDeliveryClaim",
    "claimSubmitted",
    "cancellationBuilder",
    "cancellationConfirmed",
}

PRIMARY_A2UI_COMPONENTS = {
    "welcome",
    "orderSelection",
    "promiseDashboard",
    "wrongDeliveryClaim",
    "claimSubmitted",
    "cancellationBuilder",
    "cancellationConfirmed",
}


class IntentExtraction(BaseModel):
    intent: Literal[
        "WHERE_IS_MY_ORDER",
        "SELECT_ORDER",
        "WRONG_DELIVERY",
        "SUBMIT_WRONG_DELIVERY_CLAIM",
        "ORDER_NOT_LISTED",
        "CANCEL_ORDER",
        "UNKNOWN",
    ] = Field(description="The customer's support intent.")

    orderNumber: Optional[str] = Field(
        default=None,
        description="The Unicorn order number if present, for example U-1002.",
    )

    issueType: Optional[str] = Field(
        default=None,
        description=(
            "Use wrong_delivery when the customer says the delivered package is "
            "missing, delivered to the wrong address, or not received."
        ),
    )


class CustomerExplanation(BaseModel):
    assistantMessage: str = Field(
        description="Professional, empathetic, customer-facing explanation."
    )


class A2UIPlannerComponent(BaseModel):
    type: Literal[
        "welcome",
        "orderSelection",
        "promiseDashboard",
        "deliveryProof",
        "serviceRecovery",
        "wrongDeliveryClaim",
        "claimSubmitted",
        "cancellationBuilder",
        "cancellationConfirmed",
    ] = Field(description="Approved A2UI component type.")

    props: Dict[str, Any] = Field(
        default_factory=dict,
        description="Small structured props for the component. Do not include full order payloads.",
    )


class A2UIPlannerOutput(BaseModel):
    components: List[A2UIPlannerComponent] = Field(
        description="Ordered list of approved A2UI components to render."
    )


def extract_order_number_from_text(user_message: str) -> Optional[str]:
    match = re.search(r"\bU-\d{4}\b", user_message.upper())

    if match:
        return match.group(0)

    return None


# Short, deliberate phrase list for the non-LLM fallback path only: these
# phrases are ambiguous on their own (no order number, no explicit "where is
# my order"), so they only resolve to SELECT_ORDER when pageContext confirms
# the customer is already looking at a specific order's details page.
ORDER_STATUS_INQUIRY_PHRASES = (
    "why is this late",
    "why is it late",
    "why is my order late",
    "why is this delayed",
    "why is it delayed",
    "when will it arrive",
    "when will this arrive",
    "when will my order arrive",
    "what is the status",
    "what's the status",
    "is this delayed",
    "is it delayed",
    "track this order",
    "track this",
)


# Short, deliberate phrase list for the non-LLM fallback path: the customer
# wants to cancel an order (checked ahead of the generic order-number and
# "where is my order" branches, so "cancel order U-1004" resolves to
# CANCEL_ORDER rather than SELECT_ORDER).
CANCEL_ORDER_PHRASES = (
    "cancel an order",
    "cancel my order",
    "cancel order",
    "cancel this order",
    "i want to cancel",
    "i'd like to cancel",
    "want to cancel",
)


# Short, deliberate phrase list for the non-LLM fallback path: the customer
# says the order they're looking for isn't among the options just shown.
ORDER_NOT_LISTED_PHRASES = (
    "isn't listed",
    "is not listed",
    "not listed here",
    "don't see my order",
    "do not see my order",
    "none of these",
    "none of those",
    "not in the list",
    "not in this list",
)


def get_order_details_page_order_number(state: AgentState) -> Optional[str]:
    page_context = state.get("pageContext") or {}

    if page_context.get("page") != "ORDER_DETAILS":
        return None

    return page_context.get("orderNumber")


def fallback_intent_detection(state: AgentState) -> AgentState:
    user_message = state.get("userMessage", "")
    user_message_lower = user_message.lower()

    extracted_order_number = extract_order_number_from_text(user_message)
    page_context_order_number = get_order_details_page_order_number(state)

    if any(phrase in user_message_lower for phrase in CANCEL_ORDER_PHRASES):
        state["intent"] = "CANCEL_ORDER"

        if extracted_order_number:
            state["orderNumber"] = extracted_order_number

    elif (
        "not delivered" in user_message_lower
        or "wrong address" in user_message_lower
        or "not my address" in user_message_lower
        or "not received" in user_message_lower
        or "don't see it" in user_message_lower
        or "do not see it" in user_message_lower
        or "missing package" in user_message_lower
        or "delivered but" in user_message_lower
    ):
        state["intent"] = "WRONG_DELIVERY"
        state["issueType"] = "wrong_delivery"

        # An order number explicitly mentioned in the message always wins
        # over the page the customer happens to be viewing.
        if extracted_order_number:
            state["orderNumber"] = extracted_order_number
        elif page_context_order_number:
            state["orderNumber"] = page_context_order_number

    elif extracted_order_number:
        state["intent"] = "SELECT_ORDER"
        state["orderNumber"] = extracted_order_number

    elif (
        "where is my order" in user_message_lower
        or "track my order" in user_message_lower
        or "where's my order" in user_message_lower
        or "where is my package" in user_message_lower
        or "where's my package" in user_message_lower
        or "order status" in user_message_lower
        or "package status" in user_message_lower
    ):
        state["intent"] = "WHERE_IS_MY_ORDER"

    elif any(phrase in user_message_lower for phrase in ORDER_NOT_LISTED_PHRASES):
        state["intent"] = "ORDER_NOT_LISTED"

    elif page_context_order_number and any(
        phrase in user_message_lower for phrase in ORDER_STATUS_INQUIRY_PHRASES
    ):
        state["intent"] = "SELECT_ORDER"
        state["orderNumber"] = page_context_order_number

    else:
        state["intent"] = "UNKNOWN"

    return state


def detect_intent_node(state: AgentState) -> AgentState:
    user_message = state.get("userMessage", "")

    if not os.getenv("OPENAI_API_KEY"):
        return fallback_intent_detection(state)

    try:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        llm = ChatOpenAI(
            model=model_name,
            temperature=0,
        )

        structured_llm = llm.with_structured_output(IntentExtraction)

        result = structured_llm.invoke(
            [
                (
                    "system",
                    """
You are the intent and entity extraction layer for Uni, a retail support assistant for a fictional D2C apparel brand called Unicorn.

Return only the structured fields requested by the schema.

Allowed intents:
- WHERE_IS_MY_ORDER: customer wants to see recent orders, track an order generally, asks where their order/package is, or wants order status without a specific order number.
- SELECT_ORDER: customer selected or mentioned a specific order number, such as U-1002, and wants tracking, delivery, promise, or delay status.
- WRONG_DELIVERY: tracking says delivered but customer says package is missing, not received, delivered to the wrong address, or the delivery photo does not match their address.
- SUBMIT_WRONG_DELIVERY_CLAIM: customer is submitting a wrong-delivery claim form.
- ORDER_NOT_LISTED: customer says the order they're looking for isn't shown among recent orders just presented, or none of the options match.
- CANCEL_ORDER: customer wants to cancel an order, or cancel items from an order.
- UNKNOWN: message is unrelated or not clear.

Rules:
- If a message contains an order number like U-1002 and asks to track/check/review it, use SELECT_ORDER.
- If a message contains an order number and says it is late or delayed, use SELECT_ORDER.
- If a message says delivered but not received, wrong address, not my door, not my porch, or does not see package, use WRONG_DELIVERY.
- If the customer says their order isn't listed, isn't shown, or none of the presented options match, use ORDER_NOT_LISTED.
- If the customer wants to cancel an order, use CANCEL_ORDER even if an order number is also mentioned — cancellation intent takes priority over a plain tracking request.
- Extract orderNumber exactly if present.
- Set issueType to wrong_delivery only for wrong delivery or delivered-but-not-received cases.
- Do not invent order numbers.
- The input may also include pageContext describing the page the customer is currently viewing. If pageContext.page is ORDER_DETAILS and the customer refers to "this order" or asks about its delay, status, or tracking without naming an order number, use SELECT_ORDER (or WRONG_DELIVERY if applicable) and set orderNumber to pageContext.orderNumber. An order number explicitly stated in the message always overrides pageContext.
""",
                ),
                (
                    "human",
                    json.dumps(
                        {
                            "customerMessage": user_message,
                            "pageContext": state.get("pageContext"),
                        }
                    ),
                ),
            ]
        )

        state["intent"] = result.intent

        if result.orderNumber:
            state["orderNumber"] = result.orderNumber.upper()

        extracted_order_number = extract_order_number_from_text(user_message)
        if extracted_order_number and not state.get("orderNumber"):
            state["orderNumber"] = extracted_order_number

        if not state.get("orderNumber") and result.intent in {
            "SELECT_ORDER",
            "WRONG_DELIVERY",
        }:
            page_context_order_number = get_order_details_page_order_number(state)
            if page_context_order_number:
                state["orderNumber"] = page_context_order_number

        if result.issueType:
            state["issueType"] = result.issueType

        if result.intent == "WRONG_DELIVERY" and not state.get("issueType"):
            state["issueType"] = "wrong_delivery"

        return state

    except Exception as exc:
        print(f"LLM intent extraction failed. Falling back to rules. Error: {exc}")
        return fallback_intent_detection(state)


def load_data_node(state: AgentState) -> AgentState:
    intent = state.get("intent")

    try:
        if intent == "WHERE_IS_MY_ORDER":
            recent_orders_data = get_recent_orders()
            state["recentOrdersData"] = recent_orders_data

        elif intent == "SELECT_ORDER":
            order_number = state.get("orderNumber")

            if not order_number:
                state["error"] = "Order number is missing."
                return state

            dashboard_data = get_order_promise_dashboard(order_number)
            state["promiseDashboardData"] = dashboard_data

            packages = dashboard_data.get("packages", [])
            if packages:
                first_package_promise = packages[0].get("promise", {}) or {}
                state["promiseResult"] = first_package_promise.get("promiseResult")
                state["promiseReasonCode"] = first_package_promise.get(
                    "promiseReasonCode"
                )

        elif intent == "WRONG_DELIVERY":
            state["issueType"] = "wrong_delivery"

            order_number = state.get("orderNumber")
            if order_number:
                dashboard_data = get_order_promise_dashboard(order_number)
                state["promiseDashboardData"] = dashboard_data

                packages = dashboard_data.get("packages", [])
                if packages:
                    first_package_promise = packages[0].get("promise", {}) or {}
                    state["promiseResult"] = first_package_promise.get(
                        "promiseResult"
                    )
                    state["promiseReasonCode"] = first_package_promise.get(
                        "promiseReasonCode"
                    )

        elif intent == "CANCEL_ORDER":
            state["cancellationEligibleOrdersData"] = get_cancellation_eligible_orders()

    except Exception as exc:
        state["error"] = str(exc)

    return state


def retrieve_policy_node(state: AgentState) -> AgentState:
    if state.get("error"):
        return state

    intent = state.get("intent")

    try:
        if intent == "SELECT_ORDER":
            state["policyData"] = retrieve_policy_context(
                promise_result=state.get("promiseResult"),
                reason_code=state.get("promiseReasonCode"),
            )

        elif intent == "WRONG_DELIVERY":
            state["policyData"] = retrieve_policy_context(
                issue_type=state.get("issueType") or "wrong_delivery",
            )

        elif intent == "CANCEL_ORDER":
            state["policyData"] = retrieve_policy_context(
                issue_type="cancel_order",
            )

    except Exception as exc:
        state["error"] = str(exc)

    return state


def generate_explanation_node(state: AgentState) -> AgentState:
    if state.get("error"):
        return state

    intent = state.get("intent")

    if intent not in {"SELECT_ORDER", "WRONG_DELIVERY"}:
        return state

    if not os.getenv("OPENAI_API_KEY"):
        return state

    try:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        llm = ChatOpenAI(
            model=model_name,
            temperature=0.2,
            max_tokens=160,
        )

        structured_llm = llm.with_structured_output(CustomerExplanation)

        dashboard_data = state.get("promiseDashboardData", {})
        policy_data = state.get("policyData", {})

        explanation_input = {
            "customerMessage": state.get("userMessage"),
            "intent": intent,
            "orderNumber": state.get("orderNumber"),
            "promiseResult": state.get("promiseResult"),
            "promiseReasonCode": state.get("promiseReasonCode"),
            "dashboardData": dashboard_data,
            "retrievedPolicyFiles": policy_data.get("retrievedPolicyFiles", []),
            "policyContext": policy_data.get("policyContext", ""),
        }

        result = structured_llm.invoke(
            [
                (
                    "system",
                    """
You are Uni, a professional and empathetic customer support assistant for Unicorn, a fictional premium D2C apparel brand.

Your job is to write a concise customer-facing explanation.

Use only the facts provided in the order data, tracking data, service recovery actions, and policy context.

Tone:
- Warm
- Professional
- Clear
- Brand-safe
- Empathetic without over-apologizing

Length and structure — this is the most important rule:
- 1 to 3 short sentences, no more than about 60-70 words total, no exceptions.
- Lead with the outcome or status first (e.g. "Order U-1002 shows delivered on May 8" or "Order U-1001 was delivered on May 4 and May 5, both before the May 6 promise date").
- Cite the specific dates, order number, and package count already present in the provided data instead of speaking in generalities — be concrete, not vague.
- Say only what the customer needs to know right now. A separate visual component will show package-by-package detail, timelines, and next actions — do not restate that detail in prose, and do not describe or refer to the UI itself.
- Never say the same fact twice in different words within one message — state each fact exactly once, then stop.
- Never end with generic closing filler such as "let me know if you need anything else," "feel free to reach out," or "please don't hesitate to contact us" — suggested actions and a message box are already visible to the customer, so this is redundant.

Customer-facing rules:
- Do not mention internal policy retrieval, RAG, LangGraph, A2UI, tools, backend systems, or implementation details.
- Do not mention customer loyalty tier, lifetime value, or internal eligibility logic.
- Do not show confidence percentages.
- Do not blame the customer.
- Do not blame the carrier aggressively.
- Do not invent refunds, coupons, replacements, credits, claim approvals, or outcomes.
- Only mention a refund, coupon, or other recovery action when the instructions for the current intent below say to.

For late delivery:
One sentence stating whether it arrived on time or late, with the actual and promised dates. If a shipping refund or coupon is present in the data, add a short second clause naming it. Nothing else.

For weather delay:
One sentence stating the delay and the new delivery expectation. If a goodwill offer is present in the data, add a short second clause naming it. Nothing else.

For wrong delivery:
One sentence: acknowledge the tracking shows delivered (with the delivery date) and say you'll help submit a wrong-delivery claim. Mention the 1–2 day investigation SLA only if supported by policy context. Do not mention refunds, coupons, or the original delivery promise here — that is not what the customer is asking about right now.
""",
                ),
                ("human", json.dumps(explanation_input, indent=2)),
            ]
        )

        state["customerExplanation"] = result.assistantMessage

    except Exception as exc:
        print(f"LLM explanation generation failed. Using fallback message. Error: {exc}")

    return state


def build_default_a2ui_payload(state: AgentState) -> list[dict]:
    intent = state.get("intent")
    dashboard_data = state.get("promiseDashboardData", {})
    summary = dashboard_data.get("summary", {}) if dashboard_data else {}
    order = dashboard_data.get("order", {}) if dashboard_data else {}

    if intent == "WHERE_IS_MY_ORDER":
        return [
            {
                "type": "orderSelection",
                "props": {
                    "customerDataKey": "customer",
                    "ordersDataKey": "orders",
                },
            }
        ]

    if intent == "SELECT_ORDER":
        has_delivery_proof = bool(summary.get("hasDeliveryProof"))
        has_service_recovery = bool(summary.get("hasServiceRecovery"))

        components = [
            {
                "type": "promiseDashboard",
                "props": {
                    "dataKey": "selectedOrder",
                    "orderNumber": order.get("orderNumber") or state.get("orderNumber"),
                    "promiseStatus": summary.get("overallPromiseStatus"),
                },
            }
        ]

        if has_delivery_proof:
            components.append(
                {
                    "type": "deliveryProof",
                    "props": {
                        "enabled": True,
                        "dataKey": "selectedOrder.packages",
                    },
                }
            )

        if has_service_recovery:
            components.append(
                {
                    "type": "serviceRecovery",
                    "props": {
                        "enabled": True,
                        "dataKey": "selectedOrder.serviceRecoveryActions",
                    },
                }
            )

        return components

    if intent == "WRONG_DELIVERY":
        return [
            {
                "type": "wrongDeliveryClaim",
                "props": {
                    "dataKey": "selectedOrder",
                    "issueType": "wrong_delivery",
                    "includeDeliveryProof": bool(dashboard_data),
                },
            }
        ]

    if intent == "SUBMIT_WRONG_DELIVERY_CLAIM":
        return [
            {
                "type": "claimSubmitted",
                "props": {
                    "dataKey": "claimResult",
                },
            }
        ]

    if intent == "ORDER_NOT_LISTED":
        return [
            {
                "type": "welcome",
                "props": {},
            }
        ]

    if intent == "CANCEL_ORDER":
        return [
            {
                "type": "cancellationBuilder",
                "props": {
                    "dataKey": "eligibleOrders",
                },
            }
        ]

    return [
        {
            "type": "welcome",
            "props": {},
        }
    ]


def validate_a2ui_components(
    raw_components: list[dict],
    fallback_components: list[dict],
) -> list[dict]:
    validated_components = []

    for component in raw_components:
        component_type = component.get("type")
        props = component.get("props") or {}

        if component_type not in ALLOWED_A2UI_COMPONENTS:
            continue

        if not isinstance(props, dict):
            props = {}

        validated_components.append(
            {
                "type": component_type,
                "props": props,
            }
        )

    has_primary_component = any(
        component["type"] in PRIMARY_A2UI_COMPONENTS
        for component in validated_components
    )

    if not validated_components or not has_primary_component:
        return fallback_components

    return validated_components


def plan_a2ui_node(state: AgentState) -> AgentState:
    if state.get("error"):
        return state

    fallback_components = build_default_a2ui_payload(state)

    if not os.getenv("OPENAI_API_KEY"):
        state["a2uiComponents"] = fallback_components
        return state

    try:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        llm = ChatOpenAI(
            model=model_name,
            temperature=0,
        )

        structured_llm = llm.with_structured_output(
                    A2UIPlannerOutput,
                    method="function_calling",
                )

        dashboard_data = state.get("promiseDashboardData", {})
        recent_orders_data = state.get("recentOrdersData", {})
        summary = dashboard_data.get("summary", {}) if dashboard_data else {}
        policy_data = state.get("policyData", {})

        planner_input = {
            "customerMessage": state.get("userMessage"),
            "intent": state.get("intent"),
            "orderNumber": state.get("orderNumber"),
            "promiseResult": state.get("promiseResult"),
            "promiseReasonCode": state.get("promiseReasonCode"),
            "issueType": state.get("issueType"),
            "orderSummary": summary,
            "hasRecentOrders": bool(recent_orders_data.get("orders")),
            "hasSelectedOrder": bool(dashboard_data),
            "retrievedPolicyFiles": policy_data.get("retrievedPolicyFiles", []),
            "defaultComponents": fallback_components,
        }

        result = structured_llm.invoke(
            [
                (
                    "system",
                    """
You are the A2UI UI Planner for Uni, a retail support assistant.

You choose which approved UI components should be rendered in the support workspace.

You must only choose from this approved component catalog:

1. welcome
Purpose: Default landing screen or unclear intent.

2. orderSelection
Purpose: Show recent orders for the customer to choose from.
Use when intent is WHERE_IS_MY_ORDER.

3. promiseDashboard
Purpose: Show selected order status, package timeline, promise status, delivery proof section, and service recovery section.
Use when intent is SELECT_ORDER and an order is available.

4. deliveryProof
Purpose: Supplemental instruction that delivery proof should be available inside the promise dashboard.
Use only when order summary says hasDeliveryProof is true.

5. serviceRecovery
Purpose: Supplemental instruction that service recovery should be available inside the promise dashboard.
Use only when order summary says hasServiceRecovery is true.

6. wrongDeliveryClaim
Purpose: Show wrong-delivery claim form.
Use when intent is WRONG_DELIVERY.

7. claimSubmitted
Purpose: Show claim confirmation screen.
Use when intent is SUBMIT_WRONG_DELIVERY_CLAIM.

8. cancellationBuilder
Purpose: Show the cancellation-eligible orders and let the customer select items/quantities to cancel.
Use when intent is CANCEL_ORDER.

9. cancellationConfirmed
Purpose: Show cancellation confirmation screen. Only produced after a real submission — never select this yourself.

Rules:
- Return only the structured schema.
- Do not invent component types.
- Do not include arbitrary React, HTML, or CSS.
- Always include one primary component:
  welcome, orderSelection, promiseDashboard, wrongDeliveryClaim, claimSubmitted, or cancellationBuilder.
- For SELECT_ORDER, primary component should be promiseDashboard.
- For WHERE_IS_MY_ORDER, primary component should be orderSelection.
- For WRONG_DELIVERY, primary component should be wrongDeliveryClaim.
- For ORDER_NOT_LISTED, primary component should be welcome.
- For CANCEL_ORDER, primary component should be cancellationBuilder.
- Include deliveryProof only if hasDeliveryProof is true.
- Include serviceRecovery only if hasServiceRecovery is true.
- Props should be small and declarative. Use dataKey references instead of embedding full data.
""",
                ),
                ("human", json.dumps(planner_input, indent=2)),
            ]
        )

        raw_components = [
            component.model_dump() for component in result.components
        ]

        state["a2uiComponents"] = validate_a2ui_components(
            raw_components,
            fallback_components,
        )

    except Exception as exc:
        print(f"LLM UI planner failed. Using fallback A2UI. Error: {exc}")
        state["a2uiComponents"] = fallback_components

    return state


def get_a2ui_components(state: AgentState) -> list[dict]:
    components = state.get("a2uiComponents")

    if components:
        return components

    return build_default_a2ui_payload(state)


def build_ui_state_node(state: AgentState) -> AgentState:
    intent = state.get("intent", "UNKNOWN")
    error = state.get("error")

    if error:
        state["uiState"] = {
            "uiMode": "welcome",
            "assistantMessage": (
                "I’m sorry, I couldn’t load that information right now. "
                "Please try again in a moment."
            ),
            "canvasData": {
                "error": error,
            },
            "agentSteps": [
                {"label": "Request received", "status": "complete"},
                {"label": "Data load failed", "status": "complete"},
            ],
            "a2uiVersion": "0.1",
            "a2ui": [
                {
                    "type": "welcome",
                    "props": {
                        "error": True,
                    },
                }
            ],
        }
        return state

    if intent == "WHERE_IS_MY_ORDER":
        recent_orders_data = state.get("recentOrdersData", {})

        state["uiState"] = {
            "uiMode": "orderSelection",
            "assistantMessage": "I found your recent Unicorn orders. Choose the order you’d like me to review.",
            "canvasData": {
                "customer": recent_orders_data.get("customer"),
                "orders": recent_orders_data.get("orders", []),
            },
            "agentSteps": [
                {"label": "Intent detected by LLM", "status": "complete"},
                {"label": "Recent orders retrieved", "status": "complete"},
                {"label": "A2UI component catalog evaluated", "status": "complete"},
                {"label": "Order selection ready", "status": "complete"},
            ],
            "suggestedReplies": ["My order isn't listed"],
            "a2uiVersion": "0.1",
            "a2ui": get_a2ui_components(state),
        }

    elif intent == "SELECT_ORDER":
        order_number = state.get("orderNumber")
        dashboard_data = state.get("promiseDashboardData", {})
        summary = dashboard_data.get("summary", {})
        policy_data = state.get("policyData", {})

        state["uiState"] = {
            "uiMode": "promiseDashboard",
            "assistantMessage": state.get("customerExplanation")
            or summary.get(
                "customerMessage",
                f"I reviewed order {order_number} and found the latest promise and package status.",
            ),
            "canvasData": {
                "selectedOrder": dashboard_data,
                "policy": {
                    "retrievedPolicyFiles": policy_data.get(
                        "retrievedPolicyFiles", []
                    )
                },
            },
            "agentSteps": [
                {
                    "label": "Intent and order number extracted by LLM",
                    "status": "complete",
                },
                {"label": "Order packages loaded", "status": "complete"},
                {"label": "Tracking events reviewed", "status": "complete"},
                {"label": "Promise status evaluated", "status": "complete"},
                {"label": "Service policy retrieved", "status": "complete"},
                {"label": "Customer explanation generated", "status": "complete"},
                {"label": "LLM selected A2UI components", "status": "complete"},
                {"label": "A2UI component list validated", "status": "complete"},
                {"label": "Canvas update ready", "status": "complete"},
            ],
            "a2uiVersion": "0.1",
            "a2ui": get_a2ui_components(state),
        }

    elif intent == "WRONG_DELIVERY":
        policy_data = state.get("policyData", {})
        dashboard_data = state.get("promiseDashboardData", {})

        state["uiState"] = {
            "uiMode": "wrongDeliveryClaim",
            "assistantMessage": state.get("customerExplanation")
            or (
                "I’m sorry about that. I’ll open a delivery claim form "
                "so our service team can investigate."
            ),
            "canvasData": {
                "selectedOrder": dashboard_data or None,
                "policy": {
                    "retrievedPolicyFiles": policy_data.get(
                        "retrievedPolicyFiles", []
                    )
                },
            },
            "agentSteps": [
                {"label": "Delivery issue detected by LLM", "status": "complete"},
                {"label": "Wrong-delivery policy retrieved", "status": "complete"},
                {"label": "Customer explanation generated", "status": "complete"},
                {"label": "LLM selected A2UI claim form", "status": "complete"},
                {"label": "A2UI component list validated", "status": "complete"},
                {"label": "Claim form prepared", "status": "complete"},
            ],
            "a2uiVersion": "0.1",
            "a2ui": get_a2ui_components(state),
        }

    elif intent == "ORDER_NOT_LISTED":
        state["uiState"] = {
            "uiMode": "welcome",
            "assistantMessage": (
                "No problem — tell me roughly when you placed the order, or "
                "what it included, and I'll help track it down."
            ),
            "canvasData": {},
            "agentSteps": [
                {"label": "Intent detected", "status": "complete"},
                {"label": "Alternate search options prepared", "status": "complete"},
            ],
            "suggestedReplies": ["Where is my order?"],
            "a2uiVersion": "0.1",
            "a2ui": get_a2ui_components(state),
        }

    elif intent == "CANCEL_ORDER":
        eligible_data = state.get("cancellationEligibleOrdersData", {})
        eligible_orders = eligible_data.get("orders", [])

        if eligible_orders:
            assistant_message = (
                "Here are the orders you can still cancel. Select one to get started."
            )
        else:
            assistant_message = (
                "I don't see any orders that are still eligible for cancellation "
                "right now — orders can only be cancelled before they ship."
            )

        state["uiState"] = {
            "uiMode": "cancellationBuilder",
            "assistantMessage": assistant_message,
            "canvasData": {
                "customer": eligible_data.get("customer"),
                "eligibleOrders": eligible_orders,
            },
            "agentSteps": [
                {"label": "Intent detected", "status": "complete"},
                {"label": "Cancellation-eligible orders retrieved", "status": "complete"},
            ],
            "a2uiVersion": "0.1",
            "a2ui": get_a2ui_components(state),
        }

    else:
        state["uiState"] = {
            "uiMode": "welcome",
            "assistantMessage": (
                "I can help with order tracking, delivery promises, and delivery "
                "issues. Try asking: Where is my order?"
            ),
            "canvasData": {},
            "agentSteps": [
                {"label": "Intent unclear", "status": "complete"},
            ],
            "suggestedReplies": ["Where is my order?"],
            "a2uiVersion": "0.1",
            "a2ui": get_a2ui_components(state),
        }

    return state


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("detect_intent", detect_intent_node)
    graph.add_node("load_data", load_data_node)
    graph.add_node("retrieve_policy", retrieve_policy_node)
    graph.add_node("generate_explanation", generate_explanation_node)
    graph.add_node("plan_a2ui", plan_a2ui_node)
    graph.add_node("build_ui_state", build_ui_state_node)

    graph.set_entry_point("detect_intent")
    graph.add_edge("detect_intent", "load_data")
    graph.add_edge("load_data", "retrieve_policy")
    graph.add_edge("retrieve_policy", "generate_explanation")
    graph.add_edge("generate_explanation", "plan_a2ui")
    graph.add_edge("plan_a2ui", "build_ui_state")
    graph.add_edge("build_ui_state", END)

    return graph.compile()


agent_graph = build_graph()