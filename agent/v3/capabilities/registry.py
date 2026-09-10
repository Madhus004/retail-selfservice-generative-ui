# agent/v3/capabilities/registry.py

from typing import Dict

from v3.capabilities.cancellation import CANCELLATION_CAPABILITY
from v3.capabilities.general_assistance import GENERAL_ASSISTANCE_CAPABILITY
from v3.capabilities.order_status import ORDER_STATUS_CAPABILITY
from v3.capabilities.returns import RETURNS_CAPABILITY
from v3.capabilities.types import Capability

CAPABILITIES: Dict[str, Capability] = {
    "ORDER_STATUS": ORDER_STATUS_CAPABILITY,
    "GENERAL_ASSISTANCE": GENERAL_ASSISTANCE_CAPABILITY,
    "CANCELLATION": CANCELLATION_CAPABILITY,
    "RETURNS": RETURNS_CAPABILITY,
}


def get_capability(name: str) -> Capability:
    return CAPABILITIES[name]
