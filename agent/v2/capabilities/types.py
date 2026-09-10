# agent/v2/capabilities/types.py
#
# The Capability config shape, split into its own module so both
# registry.py and each per-capability module (order_status.py, etc.) can
# import it without a circular dependency between them.

from dataclasses import dataclass, field
from typing import Callable, List


@dataclass
class Capability:
    name: str
    description_for_classifier: str
    tools: List[Callable]
    allowed_agent_a2ui: List[str]
    mandatory_a2ui: List[str]
    policy_files: List[str]
    system_prompt: str
    sensitive_tool_names: List[str] = field(default_factory=list)
