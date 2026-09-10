# agent/data/mock_returns.py
#
# Return eligibility + returnable items, mirroring the
# agent/data/mock_orders.py `"cancellation"` flag pattern — a static,
# pre-decided per-order eligibility record, not something derived live from
# today's wall-clock date. This is deliberate: the mock orders' narrative
# dates are fixed in May 2026, while the real session date drifts forward
# independently (this demo has already been used across several real-world
# days), so computing "is this within N days of delivery" against
# datetime.now() would make every order silently go return-ineligible as
# real time passes, breaking the demo for reasons unrelated to anything a
# developer changed. `returnWindowExpiresAt` below is informational display
# text only — nothing in agent/v2/tools/returns_tools.py compares it
# against the current date.
#
# This file is new and V2-only (plan section 6) — agent/data/mock_orders.py
# itself is a protected, untouched V1 file (plan section 4) and is not
# modified to add this; MOCK_RETURNS is a separate dict keyed by the same
# order numbers, read alongside MOCK_ORDERS rather than merged into it.
#
# Eligibility, by order: U-1001 and U-1002 are both "Delivered" in
# mock_orders.py, so both are return-eligible here — a delivered order
# arriving late (U-1002, already used as the WRONG_DELIVERY demo order)
# doesn't disqualify it from being returnable too, since those are
# unrelated concerns. U-1003 is still in transit (never delivered) and
# U-1004/U-1005 haven't shipped at all (they're the CANCELLATION-eligible
# orders) — none of the three have anything to return yet.

MOCK_RETURNS = {
    "U-1001": {
        "eligible": True,
        "reason": None,
        "returnWindowExpiresAt": "2026-06-03",
        "returnMethods": ["mail", "in_store"],
        "items": [
            {
                "orderLineId": "OL-1001-1",
                "itemName": "AirKnit Running Shoes",
                "color": "Black / White",
                "size": "9",
                "price": 98.00,
                "quantity": 1,
                "returnableQuantity": 1,
            },
            {
                "orderLineId": "OL-1001-2",
                "itemName": "Performance Crew Socks",
                "color": "Heather Gray",
                "size": "M",
                "price": 15.21,
                "quantity": 2,
                "returnableQuantity": 2,
            },
        ],
    },
    "U-1002": {
        "eligible": True,
        "reason": None,
        "returnWindowExpiresAt": "2026-06-07",
        "returnMethods": ["mail", "in_store"],
        "items": [
            {
                "orderLineId": "OL-1002-1",
                "itemName": "Classic Denim Jacket",
                "color": "Indigo",
                "size": "M",
                "price": 79.22,
                "quantity": 1,
                "returnableQuantity": 1,
            },
        ],
    },
    "U-1003": {
        "eligible": False,
        "reason": "This order hasn't been delivered yet — it can be returned once it arrives.",
        "returnWindowExpiresAt": None,
        "returnMethods": [],
        "items": [],
    },
    "U-1004": {
        "eligible": False,
        "reason": "This order hasn't shipped yet, so there's nothing to return — it may still be eligible for cancellation instead.",
        "returnWindowExpiresAt": None,
        "returnMethods": [],
        "items": [],
    },
    "U-1005": {
        "eligible": False,
        "reason": "This order hasn't shipped yet, so there's nothing to return — it may still be eligible for cancellation instead.",
        "returnWindowExpiresAt": None,
        "returnMethods": [],
        "items": [],
    },
}
