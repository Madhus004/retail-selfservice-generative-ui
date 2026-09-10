# agent/v3/tools/policy_tools.py
#
# General Assistance's one tool — read-only, grounds policy answers in the
# same markdown files V1/V2 already read (agent/data/policies/*.md,
# reused via agent/tools.py's read_policy_file, never forked). Unlike the
# four transactional capabilities (which pre-load their one or two
# relevant policy files into the system prompt every turn, since they
# always need the same ones), General Assistance's topic is unpredictable
# turn to turn — a real tool call, chosen by the model, keeps every other
# turn from paying for policy text it doesn't need.

import re
from typing import Dict, List

from langchain_core.tools import tool

from tools import read_policy_file

_POLICY_KEYWORDS: Dict[str, List[str]] = {
    "delivery_promise_policy.md": [
        "delivery", "promise", "late", "shipping", "arrival", "eta", "tracking", "delayed",
    ],
    "service_recovery_policy.md": [
        "service recovery", "refund", "coupon", "compensation", "apology", "make it right",
    ],
    "order_cancellation_policy.md": ["cancel", "cancellation", "stop my order", "stop the order"],
    "return_policy.md": ["return", "exchange", "send back", "refund policy", "return window"],
    "wrong_delivery_claim_policy.md": [
        "wrong delivery", "missing package", "never received", "not received", "wrong address", "claim",
    ],
}


@tool
def search_policies_tool(topic: str) -> dict:
    """
    Look up Unicorn's actual customer-facing policy text relevant to a
    topic — e.g. "return window", "cancellation eligibility", "late
    delivery", "wrong address claim". Always call this before stating any
    policy detail (windows, eligibility rules, timeframes); never answer a
    policy question from memory. Returns the full text of whichever
    policy document(s) matched the topic.
    """

    lowered = topic.lower()
    # Word-boundary matching, not raw substring — "unrelated" contains
    # "late" as a bare substring, which would otherwise false-positive
    # against the delivery policy for a topic that has nothing to do with
    # it.
    matched_files = [
        name
        for name, keywords in _POLICY_KEYWORDS.items()
        if any(re.search(rf"\b{re.escape(kw)}\b", lowered) for kw in keywords)
    ]

    if not matched_files:
        # No clean keyword match — better to ground the answer in
        # everything we have than let the model guess at policy details.
        matched_files = list(_POLICY_KEYWORDS.keys())

    return {"policies": {name: read_policy_file(name) for name in matched_files}}
