# agent/test_v2_classifier.py
#
# Deterministic-path tests only (no real OpenAI call — OPENAI_API_KEY is
# cleared for every test in this file) so these are fast, free, and don't
# depend on whatever key happens to be present in the dev environment. This
# exercises agent/v2/classifier.py's deterministic_capability_fallback,
# which is also what a customer would see if V2 ran with no API key set at
# all, mirroring V1's own zero-key resilience path.

import pytest
from pydantic import ValidationError

from v2.classifier import CapabilityClassification, ClassificationContext, classify


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_classify_detects_order_status_with_order_number():
    result = classify("Where is order U-1002?")

    assert result.capability == "ORDER_STATUS"
    assert result.orderNumber == "U-1002"


def test_classify_detects_order_status_without_order_number():
    result = classify("Where is my order?")

    assert result.capability == "ORDER_STATUS"
    assert result.orderNumber is None


def test_classify_detects_cancellation():
    result = classify("Can you stop the shoes I ordered this morning?")

    assert result.capability == "CANCELLATION"


def test_classify_detects_returns():
    result = classify("These jeans don't fit.")

    assert result.capability == "RETURNS"


def test_classify_detects_wrong_delivery():
    result = classify("It says delivered but I never received it.")

    assert result.capability == "WRONG_DELIVERY"


def test_classify_defaults_to_clarify_when_ambiguous():
    result = classify("I need help with my order.")

    assert result.capability == "CLARIFY"


def test_classify_biases_toward_continuation_with_pending_question():
    context = ClassificationContext(
        activeCapability="RETURNS",
        pendingInterruptType="ASK_CUSTOMER",
        pendingQuestionSummary="asking why the customer is returning the item",
    )

    result = classify("Too small.", context)

    assert result.capability == "RETURNS"
    assert result.isCapabilitySwitch is False


def test_classify_detects_a_genuine_pivot_even_with_a_pending_question():
    context = ClassificationContext(
        activeCapability="RETURNS",
        pendingInterruptType="CONFIRM_ACTION",
        pendingQuestionSummary="confirming the return submission",
    )

    result = classify("Actually, cancel the shoes I ordered today instead.", context)

    assert result.capability == "CANCELLATION"
    assert result.isCapabilitySwitch is True


def test_capability_classification_rejects_an_invalid_capability_value():
    with pytest.raises(ValidationError):
        CapabilityClassification(
            capability="NOT_A_REAL_CAPABILITY",
            confidence="high",
            isCapabilitySwitch=False,
            rationale="x",
        )
