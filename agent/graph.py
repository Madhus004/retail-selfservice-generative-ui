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
}

PRIMARY_A2UI_COMPONENTS = {
    "welcome",
    "orderSelection",
    "promiseDashboard",
    "wrongDeliveryClaim",
    "claimSubmitted",
}


class IntentExtraction(BaseModel):
    intent: Literal[
        "WHERE_IS_MY_ORDER",
        "SELECT_ORDER",
        "WRONG_DELIVERY",
        "SUBMIT_WRONG_DELIVERY_CLAIM",
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


def fallback_intent_detection(state: AgentState) -> AgentState:
    user_message = state.get("userMessage", "")
    user_message_lower = user_message.lower()

    extracted_order_number = extract_order_number_from_text(user_message)

    if (
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

        if extracted_order_number:
            state["orderNumber"] = extracted_order_number

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
- UNKNOWN: message is unrelated or not clear.

Rules:
- If a message contains an order number like U-1002 and asks to track/check/review it, use SELECT_ORDER.
- If a message contains an order number and says it is late or delayed, use SELECT_ORDER.
- If a message says delivered but not received, wrong address, not my door, not my porch, or does not see package, use WRONG_DELIVERY.
- Extract orderNumber exactly if present.
- Set issueType to wrong_delivery only for wrong delivery or delivered-but-not-received cases.
- Do not invent order numbers.
""",
                ),
                ("human", user_message),
            ]
        )

        state["intent"] = result.intent

        if result.orderNumber:
            state["orderNumber"] = result.orderNumber.upper()

        extracted_order_number = extract_order_number_from_text(user_message)
        if extracted_order_number and not state.get("orderNumber"):
            state["orderNumber"] = extracted_order_number

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

Customer-facing rules:
- Do not mention internal policy retrieval, RAG, LangGraph, A2UI, tools, backend systems, or implementation details.
- Do not mention customer loyalty tier, lifetime value, or internal eligibility logic.
- Do not show confidence percentages.
- Do not blame the customer.
- Do not blame the carrier aggressively.
- Do not invent refunds, coupons, replacements, credits, claim approvals, or outcomes.
- If a recovery action is already present in the data, explain it clearly.
- If a shipping refund is present in the data, say the shipping fee was refunded.
- If a coupon code is present in the data, mention the code by name.
- If delivery proof is available and the customer reports wrong delivery, acknowledge the concern and say you’ll open a claim form.
- Keep the message to one short paragraph, maximum 3 sentences.

For late delivery:
Explain original promise vs actual delivery, then mention any applied refund/coupon if provided.

For weather delay:
Explain weather delay and new delivery expectation, then mention any goodwill offer if provided.

For wrong delivery:
Acknowledge the issue, say you’ll help submit a wrong-delivery claim, and mention the 1–2 day investigation SLA only if supported by policy context.
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

Rules:
- Return only the structured schema.
- Do not invent component types.
- Do not include arbitrary React, HTML, or CSS.
- Always include one primary component:
  welcome, orderSelection, promiseDashboard, wrongDeliveryClaim, or claimSubmitted.
- For SELECT_ORDER, primary component should be promiseDashboard.
- For WHERE_IS_MY_ORDER, primary component should be orderSelection.
- For WRONG_DELIVERY, primary component should be wrongDeliveryClaim.
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