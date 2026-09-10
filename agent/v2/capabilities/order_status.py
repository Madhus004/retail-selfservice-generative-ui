# agent/v2/capabilities/order_status.py
#
# WISMO, built fresh for V2. Deliberately does NOT import or call V1's
# fallback_intent_detection, load_data_node, or plan_a2ui_node (agent/graph.py)
# — only the shared deterministic *data* functions are reused (via the
# @tool-wrapped functions in v2/tools/order_tools.py), wrapped as tools the
# agent chooses to call turn-by-turn. See the plan's section 8.

from v2.capabilities.types import Capability
from v2.tools.order_tools import get_order_status_tool, get_recent_orders_tool

ORDER_STATUS_SYSTEM_PROMPT = """You are Uni's Order Status capability. The \
customer wants to know where an order is, its delivery status, or why it's \
late.

You have two tools available:
- get_recent_orders_tool: use this when you don't yet know which order the \
customer means.
- get_order_status_tool(order_number): use this once you know the order \
number, to get its packages, tracking, delivery promise, and any service \
recovery.

Call only the tool you actually need next — don't call a tool whose result \
you already have. If you don't yet know which order the customer means and \
more than one order exists, ask which one before answering.

Once you have enough information to answer, finish with ONE short headline \
sentence naming the outcome (e.g. "Your order is on its way and arriving \
Tuesday." or "This one arrived a few days late — here's what happened."). \
The customer's screen already shows a detailed card with the tracking \
timeline, delivery dates, and any service recovery — your message is a \
caption for that card, not a second copy of it. Do not restate dates, \
tracking numbers, or event-by-event detail in your message; that would \
just repeat what's already on screen. No generic closing filler either.

Never state an order's status, delivery date, or promise outcome unless it \
came from a tool result you actually called this turn — you may not invent \
or assume order facts.
"""

ORDER_STATUS_CAPABILITY = Capability(
    name="ORDER_STATUS",
    description_for_classifier=(
        "Customer wants to know where an order/package is, its delivery "
        "status, why it's late, or general tracking — no order number "
        "required."
    ),
    tools=[get_recent_orders_tool, get_order_status_tool],
    allowed_agent_a2ui=[
        "orderSelection",
        "orderStatus",
        "deliveryTimeline",
        "deliveryProof",
        "serviceRecovery",
        "suggestedReplies",
    ],
    mandatory_a2ui=[],
    policy_files=["delivery_promise_policy.md", "service_recovery_policy.md"],
    system_prompt=ORDER_STATUS_SYSTEM_PROMPT,
    sensitive_tool_names=[],
)
