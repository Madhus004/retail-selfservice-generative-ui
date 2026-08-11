from graph import build_ui_state_node, fallback_intent_detection


def test_order_not_listed_phrase_detected_by_fallback():
    state = {"userMessage": "My order isn't listed"}

    result = fallback_intent_detection(state)

    assert result["intent"] == "ORDER_NOT_LISTED"


def test_order_not_listed_variant_phrases_detected_by_fallback():
    messages = [
        "I don't see my order in the list",
        "None of these are my order",
        "My order is not listed here",
        "It's not in the list",
    ]

    for message in messages:
        state = {"userMessage": message}
        result = fallback_intent_detection(state)
        assert result["intent"] == "ORDER_NOT_LISTED", message


def test_order_not_listed_does_not_shadow_wrong_delivery():
    state = {"userMessage": "It says delivered but I do not see it"}

    result = fallback_intent_detection(state)

    assert result["intent"] == "WRONG_DELIVERY"


def test_where_is_my_order_ui_state_includes_suggested_reply_chip():
    state = {
        "intent": "WHERE_IS_MY_ORDER",
        "recentOrdersData": {"customer": {}, "orders": []},
    }

    result = build_ui_state_node(state)

    assert result["uiState"]["suggestedReplies"] == ["My order isn't listed"]


def test_order_not_listed_ui_state_shape():
    state = {"intent": "ORDER_NOT_LISTED"}

    result = build_ui_state_node(state)

    ui_state = result["uiState"]
    assert ui_state["uiMode"] == "welcome"
    assert ui_state["suggestedReplies"] == ["Where is my order?"]
    assert ui_state["assistantMessage"]
    assert ui_state["a2ui"] == [{"type": "welcome", "props": {}}]


def test_unknown_intent_ui_state_includes_suggested_reply_chip():
    state = {"intent": "UNKNOWN"}

    result = build_ui_state_node(state)

    assert result["uiState"]["suggestedReplies"] == ["Where is my order?"]
