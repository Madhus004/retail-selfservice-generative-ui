# agent/v3/customer.py
#
# The single mock customer's profile — extends V1's MOCK_CUSTOMER (reused
# directly, never forked, per the plan's reuse discipline) with the real
# personalization signal V3 needs to reason over: interests, recently
# viewed items, and stated preferences. Still one customer, still mocked
# data — but now a real row in SQLite instead of a hardcoded constant, so
# the schema is ready for real multi-customer support later without a
# rework (explicitly out of scope for now — see the plan's non-goals).

import json
from typing import Any, Dict

from data.mock_orders import MOCK_CUSTOMER

from v3.db import get_connection

DEMO_CUSTOMER_ID = MOCK_CUSTOMER["customerId"]

# Grounded in items that actually exist in MOCK_ORDERS (agent/data/mock_orders.py)
# rather than invented product names, so any capability that cross-references
# order history against "interests" is looking at a consistent catalog.
_DEFAULT_PROFILE_EXTRAS: Dict[str, Any] = {
    "interests": ["running shoes", "outerwear", "everyday basics"],
    "recentlyViewed": [
        {"sku": "SKU-DENIM-021", "name": "Classic Denim Jacket", "viewedAt": "2026-05-12T18:04:00"},
        {"sku": "SKU-HOOD-014", "name": "Lightweight Hoodie", "viewedAt": "2026-05-14T09:22:00"},
    ],
    "preferences": {
        "returnMethod": "mail",
        "communicationTone": "concise",
    },
}


def _default_profile() -> Dict[str, Any]:
    return {**MOCK_CUSTOMER, **_DEFAULT_PROFILE_EXTRAS}


def seed_customer_profile() -> None:
    """Idempotent — inserts the default profile only if this customer has no row yet."""

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM customer_profile WHERE customer_id = ?", (DEMO_CUSTOMER_ID,)
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO customer_profile (customer_id, profile_json) VALUES (?, ?)",
                (DEMO_CUSTOMER_ID, json.dumps(_default_profile(), default=str)),
            )


def get_customer_profile(customer_id: str = DEMO_CUSTOMER_ID) -> Dict[str, Any]:
    """
    Returns the stored profile, seeding it first if this is the very first
    read of a fresh database (keeps callers from having to know/care about
    startup ordering).
    """

    with get_connection() as conn:
        row = conn.execute(
            "SELECT profile_json FROM customer_profile WHERE customer_id = ?", (customer_id,)
        ).fetchone()

    if row is not None:
        return json.loads(row["profile_json"])

    if customer_id == DEMO_CUSTOMER_ID:
        seed_customer_profile()
        return _default_profile()

    raise KeyError(f"No customer profile found for {customer_id!r}")
