# agent/v3/classifier.py
#
# Capability classification — messages-aware from day one: recentTurnsSummary
# is derived straight from AgentStateV3.messages (the one authoritative
# history) by the caller, never a second hand-maintained summary field the
# way V2's conversationSummary was.
#
# Only ORDER_STATUS is a real transactional capability in Phase 1;
# everything else routes to GENERAL_ASSISTANCE, which is still a Phase-0-
# style "coming soon" acknowledgment until Phase 2 gives it real,
# policy-grounded teeth. UNSUPPORTED/CLARIFY as their own destinations are
# deferred until GENERAL_ASSISTANCE actually exists to need distinguishing
# from them — no point building terminal nodes for categories nothing can
# act on differently yet.

import os
import re
from typing import List, Literal, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

CapabilityName = Literal["ORDER_STATUS", "GENERAL_ASSISTANCE", "CANCELLATION", "RETURNS"]


class ClassificationContext(BaseModel):
    activeCapability: Optional[str] = None
    pendingInterruptType: Optional[Literal["ASK_CUSTOMER"]] = None
    pendingQuestionSummary: Optional[str] = None
    recentTurnsSummary: List[str] = Field(default_factory=list)


class CapabilityClassification(BaseModel):
    capability: CapabilityName = Field(
        description="ORDER_STATUS for anything about where an order/package is, its "
        "delivery status, or why it's late. CANCELLATION for anything about stopping/"
        "cancelling an order or item before it ships. RETURNS for actually sending an "
        "item back on an already-delivered order. GENERAL_ASSISTANCE for everything else."
    )
    confidence: Literal["high", "medium", "low"]
    isCapabilitySwitch: bool = Field(
        description=(
            "True only if this message asks for something different from "
            "activeCapability. False for ordinary answers to a pending "
            "question, even short ones like 'U-1002' — default to False "
            "unless the message clearly names a different goal."
        )
    )
    orderNumber: Optional[str] = Field(default=None)
    rationale: str = Field(description="One short internal sentence. Never shown to the customer.")


def extract_order_number(message: str) -> Optional[str]:
    match = re.search(r"\bU-\d{4}\b", message.upper())
    return match.group(0) if match else None


_SYSTEM_PROMPT = """You are the capability classifier for Uni, a retail support \
service agent for a fictional D2C apparel brand called Unicorn.

Decide which of the four capabilities currently available handles the \
customer's message:
- ORDER_STATUS: where an order/package is, delivery status, why it's late, \
general tracking. Examples: "Where is my order?", "Where is order U-1002?", \
"Why hasn't my package arrived yet?"
- CANCELLATION: the customer wants to stop/cancel an order or specific \
items before it ships. Examples: "Cancel my order", "I want to cancel \
U-1004", "Can I stop this order before it ships?" This is for actually \
DOING a cancellation (with a real confirmation step), not just asking \
about the cancellation policy in the abstract — a pure policy question \
("what's your cancellation policy?", "can I cancel after it ships?") stays \
GENERAL_ASSISTANCE.
- RETURNS: the customer wants to actually send an item back — wrong size, \
changed their mind, defective — on an order that's already been \
delivered. Examples: "I want to return my order", "Return the shoes from \
U-1001, wrong size", "Can I send this back?" This is for actually DOING a \
return (with a real confirmation step), not just asking about the return \
policy in the abstract — a pure policy question ("what's your return \
window?") stays GENERAL_ASSISTANCE.
- GENERAL_ASSISTANCE: everything else that's a real, on-topic retail \
question or comment — product questions, policy questions (return windows, \
cancellation eligibility, delivery promises, service recovery, wrong-\
delivery claims), small talk, and requests to actually submit a wrong-\
delivery claim (that can be explained accurately here but not yet \
completed — still route it here rather than to any of the other three).

Context fields you may receive: activeCapability (the capability already in \
progress this session, if any), pendingQuestionSummary (what the customer \
was just asked, if anything is pending), and a short recent-turn summary.

Rules:
- If pendingQuestionSummary is present, default to isCapabilitySwitch=False \
and capability=activeCapability when the message plausibly answers that \
question, however briefly ("yes", "U-1002") — judge it in context, not in \
isolation.
- Only set isCapabilitySwitch=True when the message clearly names a \
different goal or order than what's currently active.
- Extract orderNumber exactly if present. Do not invent one.
"""


def _deterministic_fallback(message: str, context: ClassificationContext) -> CapabilityClassification:
    """
    Pure keyword cascade — used only when no OPENAI_API_KEY is set or the
    LLM call fails, never as the primary path. Structurally the same shape
    as V1/V2's own fallback cascades.
    """

    lowered = message.lower()
    order_number = extract_order_number(message)

    order_status_phrases = (
        "where is my order",
        "where's my order",
        "track my order",
        "where is my package",
        "order status",
        "package status",
        "why is my order late",
        "why is it late",
        "hasn't arrived",
        "has not arrived",
    )

    cancellation_phrases = (
        "cancel my order",
        "cancel order",
        "cancel this order",
        "cancel it",
        "stop my order",
        "stop the order",
        "want to cancel",
        "like to cancel",
    )

    return_phrases = (
        "return my order",
        "return order",
        "return this order",
        "return it",
        "send it back",
        "send this back",
        "want to return",
        "like to return",
        "want a refund",
        "like a refund",
    )

    if any(phrase in lowered for phrase in return_phrases):
        capability: CapabilityName = "RETURNS"
    elif any(phrase in lowered for phrase in cancellation_phrases):
        capability = "CANCELLATION"
    elif order_number or any(phrase in lowered for phrase in order_status_phrases):
        capability = "ORDER_STATUS"
    else:
        capability = "GENERAL_ASSISTANCE"

    is_switch = bool(context.activeCapability and capability != context.activeCapability)

    return CapabilityClassification(
        capability=capability,
        confidence="medium",
        isCapabilitySwitch=is_switch,
        orderNumber=order_number,
        rationale="Deterministic fallback keyword match.",
    )


def classify(
    message: str, context: Optional[ClassificationContext] = None
) -> CapabilityClassification:
    context = context or ClassificationContext()

    if not os.getenv("OPENAI_API_KEY"):
        return _deterministic_fallback(message, context)

    try:
        llm = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
        ).with_structured_output(CapabilityClassification)

        human_payload = {
            "message": message,
            "activeCapability": context.activeCapability,
            "pendingInterruptType": context.pendingInterruptType,
            "pendingQuestionSummary": context.pendingQuestionSummary,
            "recentTurnsSummary": context.recentTurnsSummary,
        }

        result = llm.invoke([("system", _SYSTEM_PROMPT), ("human", str(human_payload))])

        if not result.orderNumber:
            extracted = extract_order_number(message)
            if extracted:
                result.orderNumber = extracted

        return result
    except Exception as exc:  # noqa: BLE001 - mirrors V1/V2's broad catch-and-fallback
        print(f"[v3.classifier] classification failed, using fallback: {exc}")
        return _deterministic_fallback(message, context)
