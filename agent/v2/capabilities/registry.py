# agent/v2/capabilities/registry.py
#
# CAPABILITIES maps a capability name to its config: which tools the LLM is
# allowed to call while that capability is active (enforced structurally via
# .bind_tools(), see graph.py), which A2UI types it may propose vs. which are
# always code-owned, its policy files, and its system-prompt fragment. This
# is what makes tool/UI scoping data-driven instead of requiring a separate
# graph per capability.
#
# All four capabilities are now registered (Phase 6 adds RETURNS, last —
# each was added by adding its own capabilities/*.py module and one line
# here, never by editing an existing capability's entry).

from v2.capabilities.cancellation import CANCELLATION_CAPABILITY
from v2.capabilities.order_status import ORDER_STATUS_CAPABILITY
from v2.capabilities.returns import RETURNS_CAPABILITY
from v2.capabilities.types import Capability
from v2.capabilities.wrong_delivery import WRONG_DELIVERY_CAPABILITY

CAPABILITIES: dict[str, Capability] = {
    "ORDER_STATUS": ORDER_STATUS_CAPABILITY,
    "CANCELLATION": CANCELLATION_CAPABILITY,
    "WRONG_DELIVERY": WRONG_DELIVERY_CAPABILITY,
    "RETURNS": RETURNS_CAPABILITY,
}


def get_capability(name: str) -> Capability:
    return CAPABILITIES[name]
