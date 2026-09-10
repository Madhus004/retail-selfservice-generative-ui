# agent/v3/capabilities/types.py
#
# The Capability config shape — same spirit as v2/capabilities/types.py,
# split into its own module so registry.py and each per-capability module
# can import it without a circular dependency. Renamed fields reflect V3's
# fine-grained, composable UI catalog (agent/v3/ui/catalog.py) rather than
# V2's whole-screen A2UI types.

from dataclasses import dataclass, field
from typing import Callable, List


@dataclass
class Capability:
    name: str
    description_for_classifier: str
    tools: List[Callable]
    # Which v3/ui/catalog.py primitive types the LLM may propose for this
    # capability's informational turns (validated, never trusted blindly —
    # see ui/catalog.py's validate_components()).
    allowed_ui_components: List[str]
    # Which primitive types are ALWAYS code-owned for this capability
    # (e.g. a confirmation card) — never influenced by an LLM proposal, by
    # construction. Empty for ORDER_STATUS (no sensitive actions); real
    # for CANCELLATION/RETURNS/WRONG_DELIVERY from Phase 3 onward.
    mandatory_ui_components: List[str]
    policy_files: List[str]
    system_prompt: str
    sensitive_tool_names: List[str] = field(default_factory=list)
