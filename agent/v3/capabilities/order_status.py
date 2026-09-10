# agent/v3/capabilities/order_status.py
#
# WISMO — V3's first real capability. Built fresh against V3's own graph
# (no orchestration reused from V1/V2), but the underlying data functions
# ARE reused directly via v3/tools/order_tools.py, per the plan.

from v3.capabilities.types import Capability
from v3.tools.order_tools import get_order_status_tool, get_recent_orders_tool
from v3.ui.catalog import (
    DELIVERY_PROOF_CARD,
    ORDER_LIST_PICKER,
    ORDER_SUMMARY_CARD,
    SERVICE_RECOVERY_BANNER,
    STATUS_PILL,
    SUGGESTED_ACTIONS,
    TRACKING_TIMELINE,
)

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
sentence naming the outcome. The customer's screen already shows a \
detailed card with the tracking timeline, delivery dates, and any service \
recovery — your message is a caption for that card, not a second copy of \
it. Do not restate dates, tracking numbers, or event-by-event detail in \
your message.

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
    allowed_ui_components=[
        ORDER_LIST_PICKER,
        ORDER_SUMMARY_CARD,
        STATUS_PILL,
        TRACKING_TIMELINE,
        DELIVERY_PROOF_CARD,
        SERVICE_RECOVERY_BANNER,
        SUGGESTED_ACTIONS,
    ],
    mandatory_ui_components=[],
    policy_files=["delivery_promise_policy.md", "service_recovery_policy.md"],
    system_prompt=ORDER_STATUS_SYSTEM_PROMPT,
    sensitive_tool_names=[],
)
