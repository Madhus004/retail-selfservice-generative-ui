from graph import fallback_intent_detection
from main import AgentChatRequest


def test_page_context_backfills_order_number_for_ambiguous_status_question():
    state = {
        "userMessage": "Why is this late?",
        "pageContext": {"page": "ORDER_DETAILS", "orderNumber": "U-1002"},
    }

    result = fallback_intent_detection(state)

    assert result["intent"] == "SELECT_ORDER"
    assert result["orderNumber"] == "U-1002"


def test_explicit_order_number_in_message_wins_over_page_context():
    state = {
        "userMessage": "Track U-1001",
        "pageContext": {"page": "ORDER_DETAILS", "orderNumber": "U-1002"},
    }

    result = fallback_intent_detection(state)

    assert result["intent"] == "SELECT_ORDER"
    assert result["orderNumber"] == "U-1001"


def test_wrong_delivery_backfills_order_number_from_page_context():
    state = {
        "userMessage": "I do not see it at my address",
        "pageContext": {"page": "ORDER_DETAILS", "orderNumber": "U-1002"},
    }

    result = fallback_intent_detection(state)

    assert result["intent"] == "WRONG_DELIVERY"
    assert result["orderNumber"] == "U-1002"


def test_wrong_delivery_explicit_order_number_wins_over_page_context():
    state = {
        "userMessage": "U-1001 is delivered but I do not see it",
        "pageContext": {"page": "ORDER_DETAILS", "orderNumber": "U-1002"},
    }

    result = fallback_intent_detection(state)

    assert result["intent"] == "WRONG_DELIVERY"
    assert result["orderNumber"] == "U-1001"


def test_ambiguous_status_question_without_page_context_stays_unknown():
    state = {"userMessage": "Why is this late?"}

    result = fallback_intent_detection(state)

    assert result["intent"] == "UNKNOWN"
    assert result.get("orderNumber") is None


def test_page_context_on_non_order_details_page_does_not_trigger_select_order():
    state = {
        "userMessage": "Why is this late?",
        "pageContext": {"page": "ORDER_HISTORY"},
    }

    result = fallback_intent_detection(state)

    assert result["intent"] == "UNKNOWN"
    assert result.get("orderNumber") is None


def test_agent_chat_request_accepts_optional_page_context():
    request = AgentChatRequest(
        message="hi",
        pageContext={"page": "ORDER_DETAILS", "orderNumber": "U-1002"},
    )
    assert request.pageContext == {"page": "ORDER_DETAILS", "orderNumber": "U-1002"}

    request_without_context = AgentChatRequest(message="hi")
    assert request_without_context.pageContext is None
