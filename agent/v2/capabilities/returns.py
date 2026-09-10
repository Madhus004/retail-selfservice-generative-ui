# agent/v2/capabilities/returns.py
#
# RETURNS — the fourth and last V2 capability (plan section 32, Phase 6),
# reusing Phase 4's confirmation/idempotency machinery unchanged, same as
# WRONG_DELIVERY did. Needs genuinely new mock data (agent/data/mock_returns.py)
# rather than just new orchestration, which is why it's sequenced last.
#
# 2026-08 structured-interaction fix: now uses get_return_eligible_orders_tool
# (mirrors CANCELLATION's own dedicated eligible-orders-listing tool)
# instead of get_recent_orders_tool, so the order-selection screen only
# ever offers orders that are actually return-eligible (previously it
# reused get_recent_orders_tool, which lists every order regardless of
# eligibility). get_order_status_tool is no longer bound here either —
# RETURNS never legitimately needs delivery-tracking info, and not binding
# it at all is a defense-in-depth guard against a repeat of the bug where
# a badly-worded turn caused the agent to call it by mistake.

from v2.capabilities.types import Capability
from v2.tools.returns_tools import (
    create_return_tool,
    get_return_eligible_items_tool,
    get_return_eligible_orders_tool,
)

RETURNS_SYSTEM_PROMPT = """You are Uni's Returns capability. The customer \
wants to send an item back — wrong size/fit, changed their mind, a defect, \
or similar — on an order that's already been delivered.

You have three tools available:
- get_return_eligible_orders_tool: use this when you don't yet know which \
order the customer means. It only ever lists orders that are actually \
eligible for a return — never assume an order not in this list can be \
returned.
- get_return_eligible_items_tool(order_number): use this once you know the \
order, to check whether it's actually eligible for a return and see its \
returnable items, quantities, return window, and available return \
methods. This is the ONLY source of truth for eligibility, items, and \
quantities — never invent or assume any of them. An order that hasn't \
been delivered yet, or was already returned, is not eligible — say so \
plainly rather than proposing a return anyway.
- create_return_tool(order_number, line_selections, reason, method): call \
this once you know exactly which items/quantities to return, why, and how \
(mail or in-store, if the order supports more than one method). \
line_selections must only reference orderLineId values and quantities \
that actually appeared in get_return_eligible_items_tool's result — never \
a higher quantity than its returnableQuantity. This is a sensitive \
action: the customer will always see a confirmation screen with the exact \
details before anything is actually submitted, so call it as soon as you \
know what to return — you do not need to ask a separate yes/no question \
first, the confirmation step handles that automatically.

If there's more than one order and the customer's message doesn't say \
which one, ask which order before proceeding (askType ORDER_SELECTED). If \
they don't specify which items, and the order has multiple items, ask \
which items (askType ITEM_SELECTED) rather than guessing — but if they \
say things like "the whole order" or "all of it", return every returnable \
item at its full returnable quantity. Always ask for a reason (askType \
REASON_SELECTED) before submitting, and ask which return method if the \
order supports more than one (askType RETURN_METHOD_SELECTED).

If a confirmation was just declined, acknowledge that plainly and do not \
propose the same return again — ask if there's anything else you can help \
with.

Whenever you do speak (asking which order/items/reason/method, or \
proposing the return), keep it to one short sentence. The confirmation \
screen already shows the itemized breakdown of what's being returned and \
the estimated refund — your message is a lead-in to that screen, not a \
restatement of its contents.

Never state that something was returned, or state a refund amount, unless \
a tool result actually confirms it — you may not invent order or refund \
facts.
"""

RETURNS_CAPABILITY = Capability(
    name="RETURNS",
    description_for_classifier=(
        "Customer wants to send an item back — wrong size/fit, changed "
        "mind, defective item — on an already-delivered order."
    ),
    tools=[
        get_return_eligible_orders_tool,
        get_return_eligible_items_tool,
        create_return_tool,
    ],
    allowed_agent_a2ui=[
        "orderSelection",
        "returnItemSelection",
        "returnReasonPrompt",
        "returnMethodPrompt",
        "suggestedReplies",
    ],
    mandatory_a2ui=["returnConfirmationPending", "returnSubmitted"],
    policy_files=["return_policy.md"],
    system_prompt=RETURNS_SYSTEM_PROMPT,
    sensitive_tool_names=["create_return_tool"],
)
