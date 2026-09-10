# agent/v2/tools/order_tools.py
#
# Wraps agent/tools.py's existing, already-tested deterministic functions as
# LangChain @tool-decorated callables the V2 agent loop can bind and call.
# The underlying business logic is imported directly, never forked — see the
# plan's section 5. get_order_promise_dashboard is deliberately exposed as
# ONE tool (get_order_status_tool), not split into separate
# tracking/promise/proof tools: it already returns one coherent payload, and
# splitting it would only add loop-step overhead for no decision-making
# benefit (the plan's section 5/9, echoing the user's own guidance).

from langchain_core.tools import tool

from tools import get_order_promise_dashboard, get_recent_orders


@tool
def get_recent_orders_tool() -> dict:
    """Look up the customer's recent orders and their delivery-promise status."""

    return get_recent_orders()


@tool
def get_order_status_tool(order_number: str) -> dict:
    """
    Look up one order's full status: packages, tracking events, delivery
    promise, delivery proof, and any service-recovery actions. order_number
    looks like U-1002.
    """

    return get_order_promise_dashboard(order_number)
