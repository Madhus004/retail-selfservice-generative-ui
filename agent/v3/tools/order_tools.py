# agent/v3/tools/order_tools.py
#
# Thin @tool wrappers around agent/tools.py's existing, already-tested
# deterministic functions — imported directly, never forked (same reuse
# discipline V2 established, per the plan). get_order_promise_dashboard
# stays exposed as ONE tool: it already returns one coherent
# tracking+promise+proof+recovery payload, and splitting it would only add
# loop-step overhead with no decision-making benefit.

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
