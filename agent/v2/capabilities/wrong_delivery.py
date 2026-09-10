# agent/v2/capabilities/wrong_delivery.py
#
# WRONG_DELIVERY — reuses Phase 4's confirmation/idempotency machinery
# unchanged (plan section 32, Phase 5); only its capability config and
# tools are new. get_order_status_tool is shared with ORDER_STATUS (the
# same object, imported, not redefined); submit_wrong_delivery_claim_tool
# is new (see v2/tools/wrong_delivery_tools.py — no V1 equivalent exists).
#
# Unlike ORDER_STATUS/CANCELLATION, this capability has no "list eligible
# orders" tool — the customer is expected to know which order they mean
# (or it's already in pageContext); if not, the agent asks for the order
# number directly as free text rather than offering a structured list.

from v2.capabilities.types import Capability
from v2.tools.order_tools import get_order_status_tool
from v2.tools.wrong_delivery_tools import submit_wrong_delivery_claim_tool

WRONG_DELIVERY_SYSTEM_PROMPT = """You are Uni's Wrong Delivery capability. \
The customer says tracking shows delivered but they never received the \
package, it went to the wrong address, or the delivery photo doesn't \
match their address.

You have two tools available:
- get_order_status_tool(order_number): use this to see the order's \
tracking, delivery events, and delivery proof. You need the order number \
first — if the customer didn't mention one, ask for it directly (e.g. \
"Which order is this about? You can give me the order number, like \
U-1002.") rather than guessing one.
- submit_wrong_delivery_claim_tool(order_number, description): call this \
once you know the order and understand what the customer is reporting. \
description should summarize what they told you. This is a sensitive \
action: the customer will always see a confirmation screen with the exact \
details before anything is actually submitted, so call it as soon as you \
have enough information — you do not need to ask a separate yes/no \
question first, the confirmation step handles that automatically.

If a confirmation was just declined, acknowledge that plainly and do not \
propose the same claim again — ask if there's anything else you can help \
with.

Whenever you do speak, keep it to one short sentence. The confirmation \
screen already shows the claim details — your message is a lead-in to \
that screen, not a restatement of its contents.

Never state that a claim was submitted, or describe delivery events, \
unless a tool result actually confirms it — you may not invent order or \
delivery facts.
"""

WRONG_DELIVERY_CAPABILITY = Capability(
    name="WRONG_DELIVERY",
    description_for_classifier=(
        "Tracking shows delivered but the customer says they never "
        "received it, it went to the wrong address, or the delivery "
        "photo doesn't match."
    ),
    tools=[get_order_status_tool, submit_wrong_delivery_claim_tool],
    allowed_agent_a2ui=["orderSelection", "wrongDeliveryClaimForm", "suggestedReplies"],
    mandatory_a2ui=["claimConfirmationPending", "claimSubmitted"],
    policy_files=["wrong_delivery_claim_policy.md"],
    system_prompt=WRONG_DELIVERY_SYSTEM_PROMPT,
    sensitive_tool_names=["submit_wrong_delivery_claim_tool"],
)
