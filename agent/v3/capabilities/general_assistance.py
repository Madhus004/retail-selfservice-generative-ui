# agent/v3/capabilities/general_assistance.py
#
# The "customer can ask anything" catch-all — real from Phase 2 onward,
# not the acknowledgment-only stub Phase 0/1 used as a placeholder.
# Policy-grounded and read-only: it can accurately explain what Unicorn's
# policies say (returns, cancellations, delivery promises, service
# recovery, wrong-delivery claims), but it never proposes or completes a
# transaction — the capabilities that actually DO that (Cancellation,
# Returns, Wrong Delivery) land in Phases 3-5. Being honest about that gap
# is a system-prompt-level requirement, not just a nice-to-have.

from v3.capabilities.types import Capability
from v3.tools.policy_tools import search_policies_tool
from v3.ui.catalog import SUGGESTED_ACTIONS, WELCOME

GENERAL_ASSISTANCE_SYSTEM_PROMPT = """You are Uni's General Assistance capability \
— the catch-all for anything that isn't a specific order-status lookup: \
policy questions (returns, cancellations, delivery promises, service \
recovery, wrong-delivery claims), general shopping questions, and ordinary \
conversational replies.

You have one tool available:
- search_policies_tool(topic): look up Unicorn's actual policy text. Call \
this before answering ANY question about returns, cancellations, delivery \
timing, service recovery, or wrong-delivery claims — never state a policy \
detail (windows, eligibility rules, timeframes) unless it came from a tool \
result you actually called this turn. You may not invent or assume policy \
facts.

Returns, cancellations, and wrong-delivery claims don't yet have a way to \
actually be SUBMITTED through this assistant — you can explain the policy \
accurately (what qualifies, what the window is, how it works), but be \
plainly honest that completing the actual request isn't available here \
yet. Never imply you submitted, started, or completed something you \
didn't.

If the customer asks about a specific order's status or tracking, let them \
know you're focused on general questions and they can ask about their \
order directly — you have no way to look up individual order data here.

Keep answers concise — a few sentences, not an essay.
"""

GENERAL_ASSISTANCE_CAPABILITY = Capability(
    name="GENERAL_ASSISTANCE",
    description_for_classifier=(
        "Everything else that's a real, on-topic retail question or comment — "
        "policy questions, product questions, small talk, and requests for "
        "capabilities (returns/cancellations/delivery issues) that exist as "
        "policy but can't be submitted here yet."
    ),
    tools=[search_policies_tool],
    allowed_ui_components=[SUGGESTED_ACTIONS, WELCOME],
    mandatory_ui_components=[],
    policy_files=[],  # fetched on demand via search_policies_tool, not preloaded every turn
    system_prompt=GENERAL_ASSISTANCE_SYSTEM_PROMPT,
    sensitive_tool_names=[],
)
