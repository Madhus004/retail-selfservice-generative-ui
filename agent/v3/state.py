# agent/v3/state.py
#
# V3's state. No relation to agent/state.py (V1) or agent/v2/state.py (V2) —
# neither of those is imported here, and this module is never imported by
# them. See the plan (now-am-i-in-humming-island.md) for the full
# rationale.
#
# Two schema changes versus V2, both direct fixes for real, traced bugs:
#
# 1. `messages` is the ONE authoritative conversational history — a real
#    LangGraph reducer channel (`add_messages`), holding actual
#    HumanMessage/AIMessage/ToolMessage objects, not a hand-rolled summary
#    a node has to remember to update. V2 had a scalar `userMessage` that
#    a structured UI selection never refreshed, so a later LLM call could
#    see stale, contradictory "customer message" text next to a fresh tool
#    result — that bug class cannot exist here, because there's no scalar
#    left to go stale. A structured selection still never becomes a
#    message (see graph.py); it updates the scratch fields below exactly
#    like V2 did, and its downstream tool call is what naturally appears
#    in `messages`.
#
# 2. `toolCallLog` is an ORDERED LIST, not a dict keyed by tool name. V2's
#    `toolResults[tool_name] = result` meant a second call to the same
#    tool (e.g. get_order_status_tool for a different order) silently
#    overwrote the first — the exact mechanism that made a customer who'd
#    just picked a new order see an answer about an old one. Deterministic
#    reasoning gets the same "give me the latest result" convenience via
#    graph.py's latest_tool_result() helper, but nothing is ever lost.

from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

CapabilityName = Literal[
    "ORDER_STATUS",
    "RETURNS",
    "CANCELLATION",
    "WRONG_DELIVERY",
    "GENERAL_ASSISTANCE",
    "UNSUPPORTED",
    "CLARIFY",
]

AgentDecisionAction = Literal["CALL_TOOL", "ASK_CUSTOMER", "FINISH"]

RunStatus = Literal[
    "FINAL",
    "INTERRUPTED_ASK",
    "INTERRUPTED_CONFIRM",
    "UNSUPPORTED",
    "ERROR",
]


class ToolCallRecord(TypedDict):
    callId: str
    toolName: str
    argsSummary: Dict[str, Any]
    resultSummary: Any
    isSensitive: bool
    startedAt: str
    finishedAt: Optional[str]
    error: Optional[str]


class PendingAction(TypedDict):
    actionId: str
    actionType: Literal[
        "CREATE_RETURN",
        "SUBMIT_CANCELLATION",
        "SUBMIT_WRONG_DELIVERY_CLAIM",
    ]
    capability: CapabilityName
    proposedPayload: Dict[str, Any]
    payloadHash: str
    eligibilityChecked: bool
    createdAt: str
    consumed: bool
    executed: bool


class AgentStateV3(TypedDict, total=False):
    # The one authoritative conversational history. Every node that
    # produces a message returns {"messages": [...]}; LangGraph's
    # add_messages reducer appends it — no manual list-building anywhere.
    messages: Annotated[List[BaseMessage], add_messages]

    # Session / identity / context
    threadId: str
    customerId: str
    pageContext: Optional[Dict[str, Any]]

    # Capability routing — carried forward from V2's proven design
    activeCapability: Optional[CapabilityName]
    previousCapability: Optional[CapabilityName]
    capabilityTransition: Optional[Dict[str, Any]]
    lastKnownOrderNumber: Optional[str]
    _classification: Optional[Dict[str, Any]]
    _pendingPivot: Optional[Dict[str, Any]]

    # agent_reason's per-iteration decision
    _decision: Optional[Dict[str, Any]]

    # Structured-selection scratch fields — carried forward from V2.
    # Deliberately never merged into `messages` (see module docstring).
    _structuredSelection: Optional[Dict[str, Any]]
    _selectedLineItems: Optional[List[Dict[str, Any]]]
    _selectedReason: Optional[str]
    _selectedReturnMethod: Optional[str]
    _reAsk: Optional[bool]

    # Loop safety — carried forward from V2
    loopIteration: int
    repeatedCallSignatures: List[str]
    _repeatedCallStage: Optional[str]
    _escalationReason: Optional[str]

    # Tool execution — the ordered log (see module docstring point 2)
    toolCallLog: List[ToolCallRecord]

    # Sensitive-action / confirmation machinery — carried forward from V2
    _confirmationReply: Optional[Dict[str, Any]]
    _confirmationReminder: Optional[bool]
    _confirmationDryRunFailed: Optional[bool]
    _confirmationInvalid: Optional[str]
    _confirmationDeclined: Optional[bool]
    _mandatoryUi: Optional[List[Dict[str, Any]]]
    pendingAction: Optional[PendingAction]
    archivedPendingActions: List[PendingAction]
    clarifyAttempts: int

    # A2UI (V3's fine-grained, composable catalog — see v3/ui/)
    a2uiProposal: Optional[List[Dict[str, Any]]]
    a2uiComponents: List[Dict[str, Any]]
    a2uiOrigin: Literal["AGENT_PROPOSED", "DETERMINISTIC_FALLBACK", "MANDATORY_DETERMINISTIC"]
    uiState: Dict[str, Any]
    status: RunStatus
    error: Optional[str]
