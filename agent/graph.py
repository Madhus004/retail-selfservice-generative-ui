import json
import os
import re
from typing import Literal, Optional

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
                {"label": "Order selection ready", "status": "complete"},
            ],
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
                {"label": "Canvas update ready", "status": "complete"},
            ],
        }

    elif intent == "WRONG_DELIVERY":
        policy_data = state.get("policyData", {})
        dashboard_data = state.get("promiseDashboardData", {})

        state["uiState"] = {
            "uiMode": "wrongDeliveryClaim",
            "assistantMessage": state.get("customerExplanation")
            or (
                "I’m sorry about that. I’ll open a wrong-delivery claim form "
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
                {"label": "Claim form prepared", "status": "complete"},
            ],
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
        }

    return state


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("detect_intent", detect_intent_node)
    graph.add_node("load_data", load_data_node)
    graph.add_node("retrieve_policy", retrieve_policy_node)
    graph.add_node("generate_explanation", generate_explanation_node)
    graph.add_node("build_ui_state", build_ui_state_node)

    graph.set_entry_point("detect_intent")
    graph.add_edge("detect_intent", "load_data")
    graph.add_edge("load_data", "retrieve_policy")
    graph.add_edge("retrieve_policy", "generate_explanation")
    graph.add_edge("generate_explanation", "build_ui_state")
    graph.add_edge("build_ui_state", END)

    return graph.compile()


agent_graph = build_graph()