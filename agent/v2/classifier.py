# agent/v2/classifier.py
#
# Capability classification for V2. The LLM is the *primary* decision-maker
# here (unlike V1, where a fixed pipeline node always runs regardless of what
# the customer actually needs) — a deterministic keyword cascade exists only
# as a resilience fallback for a missing API key or an invalid/failed LLM
# call, never as the primary path. See the plan's sections 12-13 and 18a.
#
# classify() is a plain function, not a LangGraph node, deliberately: it is
# called from two places — the classify_capability graph node (fresh turns)
# and, starting in Phase 2, the router's pre-resume check for free text
# arriving while an interrupt is pending. One implementation, one prompt, so
# the two call sites can never disagree about what counts as a capability
# switch.

import os
import re
from typing import List, Literal, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

CapabilityName = Literal[
    "ORDER_STATUS",
    "RETURNS",
    "CANCELLATION",
    "WRONG_DELIVERY",
    "UNSUPPORTED",
    "CLARIFY",
]


class ClassificationContext(BaseModel):
    activeCapability: Optional[CapabilityName] = None
    pendingInterruptType: Optional[Literal["ASK_CUSTOMER", "CONFIRM_ACTION"]] = None
    pendingQuestionSummary: Optional[str] = None
    recentTurnsSummary: List[str] = Field(default_factory=list)


class CapabilityClassification(BaseModel):
    capability: CapabilityName = Field(
        description="The customer's support goal, or UNSUPPORTED/CLARIFY."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="How clearly the message maps to one capability."
    )
    isCapabilitySwitch: bool = Field(
        description=(
            "True only if this message asks for something different from "
            "activeCapability. False for ordinary answers to a pending "
            "question, even short ones like 'yes' or 'too small' — default "
            "to False unless the message clearly names a different goal."
        )
    )
    orderNumber: Optional[str] = Field(default=None)
    rationale: str = Field(
        description="One short internal sentence. Never shown to the customer."
    )


def extract_order_number(message: str) -> Optional[str]:
    match = re.search(r"\bU-\d{4}\b", message.upper())
    return match.group(0) if match else None


_SYSTEM_PROMPT = """You are the capability classifier for Uni, a retail support \
service agent for a fictional D2C apparel brand called Unicorn.

Decide which business capability the customer's message is asking for.

Allowed capabilities:
- ORDER_STATUS: where an order/package is, delivery status, why it's late, \
general tracking. Examples: "Where is my order?", "Where is order U-1002?", \
"Why hasn't my package arrived yet?"
- RETURNS: sending an already-delivered item back (wrong size/fit, changed \
mind, defective). Examples: "These jeans don't fit.", "I want to send the \
blue shirt back."
- CANCELLATION: stopping/cancelling an order or items before it ships. \
Examples: "Can you stop the shoes I ordered this morning?", "Cancel my order."
- WRONG_DELIVERY: tracking shows delivered but the customer says they never \
received it, it went to the wrong address, or the photo doesn't match. \
Examples: "It says delivered but I don't have it.", "I got two boxes but \
one of them isn't mine."
- UNSUPPORTED: a real support request, but not one of the four capabilities \
above (e.g. "Can I change my shipping address?"). Say so rather than \
misrouting it.
- CLARIFY: too vague to route yet (e.g. "I need help with my order.").

Context fields you may receive: activeCapability (the capability already in \
progress this session, if any), pendingQuestionSummary (what the customer \
was just asked, if anything is pending), and a short recent-turn summary.

Rules:
- If pendingQuestionSummary is present, default to isCapabilitySwitch=False \
and capability=activeCapability when the message plausibly answers that \
question, however briefly ("yes", "too small", "U-1002") — judge it in \
context, not in isolation.
- Only set isCapabilitySwitch=True when the message clearly names a \
different goal, order, or action than what's currently active.
- Extract orderNumber exactly if present. Do not invent one.
- Low confidence with no clear single match should be CLARIFY, not a guess.
"""


def _deterministic_fallback(message: str, context: ClassificationContext) -> CapabilityClassification:
    """
    Pure keyword cascade, structurally the same shape as V1's
    fallback_intent_detection — used only when no OPENAI_API_KEY is set or
    the LLM call fails, never as the primary path.
    """

    lowered = message.lower()
    order_number = extract_order_number(message)

    cancel_phrases = ("cancel", "stop the", "stop my order", "don't ship")
    wrong_delivery_phrases = (
        "not delivered",
        "wrong address",
        "not my address",
        "not received",
        "don't see it",
        "do not see it",
        "missing package",
        "delivered but",
        "isn't mine",
        "is not mine",
    )
    return_phrases = (
        "return",
        "send back",
        "send it back",
        "doesn't fit",
        "does not fit",
        "don't fit",
        "do not fit",
        "wrong size",
        "changed my mind",
    )
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
    # Real support requests this agent recognizes but genuinely can't act
    # on — distinct from CLARIFY (too vague to route at all). Without this
    # branch the deterministic fallback could never produce UNSUPPORTED,
    # leaving unsupported_node unreachable whenever no OPENAI_API_KEY is
    # set, which would violate this project's "fully functional with no
    # API key" standard (mirrors V1's own fallback_intent_detection ethos).
    unsupported_phrases = (
        "shipping address",
        "change my address",
        "update my address",
        "payment method",
        "credit card",
        "change my card",
        "promo code",
        "discount code",
        "gift card",
        "change my email",
        "update my email",
    )

    if context.pendingQuestionSummary and not any(
        phrase in lowered for phrase in cancel_phrases + wrong_delivery_phrases + return_phrases
    ):
        # Nothing that reads like a different goal — treat as a continuation
        # of whatever capability is already active.
        if context.activeCapability and context.activeCapability not in (
            "UNSUPPORTED",
            "CLARIFY",
        ):
            return CapabilityClassification(
                capability=context.activeCapability,
                confidence="medium",
                isCapabilitySwitch=False,
                orderNumber=order_number,
                rationale="Deterministic fallback: no switch signal, pending question present.",
            )

    if any(phrase in lowered for phrase in cancel_phrases):
        capability = "CANCELLATION"
    elif any(phrase in lowered for phrase in wrong_delivery_phrases):
        capability = "WRONG_DELIVERY"
    elif any(phrase in lowered for phrase in return_phrases):
        capability = "RETURNS"
    elif order_number or any(phrase in lowered for phrase in order_status_phrases):
        capability = "ORDER_STATUS"
    elif any(phrase in lowered for phrase in unsupported_phrases):
        capability = "UNSUPPORTED"
    else:
        capability = "CLARIFY"

    is_switch = bool(
        context.activeCapability
        and context.activeCapability not in ("UNSUPPORTED", "CLARIFY")
        and capability != context.activeCapability
    )

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

        result = llm.invoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", str(human_payload)),
            ]
        )

        if not result.orderNumber:
            extracted = extract_order_number(message)
            if extracted:
                result.orderNumber = extracted

        return result
    except Exception as exc:  # noqa: BLE001 - mirrors V1's broad catch-and-fallback
        print(f"[v2.classifier] classification failed, using fallback: {exc}")
        return _deterministic_fallback(message, context)
