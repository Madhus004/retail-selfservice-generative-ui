# agent/v2/state.py
#
# V2's own state model. No relation to agent/state.py (V1) — V1's AgentState
# is untouched and this module is never imported by it. See the plan
# (now-am-i-in-humming-island.md) section 7 for the full design rationale.
#
# Phase 1 only exercises a subset of these fields (userMessage, pageContext,
# activeCapability, toolLog, loopIteration, toolResults, a2ui*, uiState,
# status). The remaining fields (pendingAction, _pendingPivot,
# lastOfferedCandidates, capabilityTransition, etc.) are declared now so
# later phases (checkpointing, confirmation, capability switching) are
# additive to this file rather than requiring a reshape.

from typing import Any, Dict, List, Literal, Optional, TypedDict

CapabilityName = Literal[
    "ORDER_STATUS",
    "RETURNS",
    "CANCELLATION",
    "WRONG_DELIVERY",
    "UNSUPPORTED",
    "CLARIFY",
]

AgentDecisionAction = Literal["CALL_TOOL", "ASK_CUSTOMER", "FINISH"]

PendingInterruptType = Literal["ASK_CUSTOMER", "CONFIRM_ACTION"]

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
    resultSummary: Dict[str, Any]
    isSensitive: bool
    startedAt: str
    finishedAt: str
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


class AgentStateV2(TypedDict, total=False):
    # Per-turn input
    userMessage: str
    pageContext: Optional[Dict[str, Any]]
    resumePayload: Optional[Dict[str, Any]]

    # Session-scoped (persisted via checkpointer once Phase 2 adds one).
    # NOTE: runId is deliberately NOT here (2026-08 runId/threadId fix) — a
    # per-HTTP-invocation identity has no business being checkpointed
    # conversation state; it's threaded through config["configurable"]
    # ["run_id"] instead and read via graph.py's _current_run_id()
    # (get_config()). Putting it here was what caused every resume to
    # double-write the same channel (the router's Command(update=
    # {"runId": ...}) colliding with every node's own full-state-dict
    # return) and raise LangGraph's InvalidUpdateError.
    threadId: str
    activeCapability: Optional[CapabilityName]
    previousCapability: Optional[CapabilityName]
    capabilityTransition: Optional[Dict[str, Any]]

    # The most recent order number any tool call actually resolved this
    # session, set by execute_tool_node whenever a tool call's args name an
    # order_number. Deliberately NOT cleared by enforce_capability_switch on
    # a capability switch (unlike toolResults/lastOfferedCandidates) — this
    # is what lets a switch like "Where is order U-1002?" -> "It says
    # delivered but I never got it." carry the order across capabilities
    # instead of re-asking, the concrete gap plan walkthrough F calls out
    # V1's stateless single-call design as unable to close.
    lastKnownOrderNumber: Optional[str]

    # Classification, set by classify_capability (or forwarded via
    # _pendingPivot when an interrupted node detects an abandon signal —
    # see the plan's section 18a). enforce_capability_switch is the only
    # reader of either.
    _classification: Optional[Dict[str, Any]]
    _pendingPivot: Optional[Dict[str, Any]]  # {"newMessage", "classification"}

    # agent_reason's structured decision for the current loop iteration,
    # consumed by the conditional edge and by execute_tool/finish. Every
    # scratch key a node writes must be declared here — LangGraph's
    # TypedDict-based state only creates a channel for declared fields, and
    # silently drops anything else between node calls.
    _decision: Optional[Dict[str, Any]]

    # A structured, code-generated UI selection (order/item/reason/method)
    # that has just passed deterministic validation in ask_customer_node
    # (candidate membership + capability match) but hasn't been applied
    # yet. agent_reason_node checks this FIRST, before any LLM call or
    # no-API-key fallback: {"type": "ORDER_SELECTED"|"ITEM_SELECTED"|
    # "REASON_SELECTED"|"RETURN_METHOD_SELECTED", "payload": {...}}.
    # Consumed (cleared) the moment it's applied — this is what guarantees
    # a structured selection is never reinterpreted by the classifier or
    # the agent's own reasoning (2026-08 structured-interaction fix).
    _structuredSelection: Optional[Dict[str, Any]]

    # Explicit line-item/quantity selections the customer made via a
    # validated ITEM_SELECTED resume — {"orderLineId", "quantity"} pairs.
    # Consulted by _deterministic_cancellation/_deterministic_returns
    # instead of their own "select everything" default once present.
    _selectedLineItems: Optional[List[Dict[str, Any]]]

    # An explicit return reason from a validated REASON_SELECTED resume.
    _selectedReason: Optional[str]

    # An explicit return method ("mail"/"in_store"/...) from a validated
    # RETURN_METHOD_SELECTED resume.
    _selectedReturnMethod: Optional[str]

    # True only when ask_customer rejected an out-of-set structured
    # selection and needs to re-interrupt with a corrective message —
    # read by the conditional edge to route back into ask_customer itself
    # rather than into agent_reason.
    _reAsk: Optional[bool]

    # Set by loop_safety.escalate() when a loop-safety limit is hit (max
    # iterations, repeated-tool-call cap, or per-tool retry cap) — the
    # reason a turn ended in escalation rather than a normal finish.
    # Distinct from the customer-facing `error` field: this one is
    # developer/trace-facing only (plan section 20/29's privacy stance).
    _escalationReason: Optional[str]

    # --- request_confirmation / execute_confirmed_action scratch fields
    # (Phase 4) — see graph.py for the full state machine these drive. ---

    # The literal {actionId, actionType, accepted} object from a real
    # Confirm/Decline button click, forwarded by request_confirmation on
    # resume for execute_confirmed_action to validate.
    _confirmationReply: Optional[Dict[str, Any]]

    # True when free text arrived during a CONFIRM_ACTION interrupt (never
    # authorization, plan section 18a correction 1) — routes back into
    # request_confirmation to re-interrupt with the SAME pendingAction.
    _confirmationReminder: Optional[bool]

    # True when the sensitive tool's dry-run preview itself raised (the
    # agent proposed an invalid action) — no interrupt ever happened this
    # pass; routes back to agent_reason instead of showing a confirmation
    # screen for something that can't actually be executed.
    _confirmationDryRunFailed: Optional[bool]

    # Set to validate_confirmation's rejection reason when a resumed
    # confirmation fails one of the 7 checks for a reason OTHER than an
    # idempotency replay (which is handled separately, returning the
    # cached result instead) — routes back to agent_reason with the stale
    # pendingAction cleared, never silently retried.
    _confirmationInvalid: Optional[str]

    # True when the customer explicitly declined a valid confirmation —
    # the pendingAction is consumed (not executed), and control returns to
    # agent_reason to respond conversationally rather than through the
    # mandatory "confirmed" UI.
    _confirmationDeclined: Optional[bool]

    # Code-owned A2UI (plan section 22/24) for a mandatory transactional
    # state — when set, finish_node uses this INSTEAD of validating the
    # agent's uiProposal, so a confirmation/completion screen can never be
    # influenced by an LLM proposal, by construction.
    _mandatoryUi: Optional[List[Dict[str, Any]]]

    conversationSummary: List[Dict[str, str]]
    toolLog: List[ToolCallRecord]
    loopIteration: int
    repeatedCallSignatures: List[str]
    # Which workflowStage repeatedCallSignatures was last recorded against
    # (2026-08 workflow-stage fix) — is_repeated_call/record_call_signature
    # reset the signature list whenever the derived workflow stage has
    # moved on, so a tool legitimately called again after the workflow
    # genuinely advances (e.g. re-checking eligibility once the customer
    # names a different order) is never blocked by a signature recorded
    # under a stage that's since been left behind. Previously this list was
    # never reset at all, so a tool call succeeding once anywhere in a
    # thread's entire history could permanently block that exact call for
    # the rest of the conversation, even across capability switches — this
    # was the direct cause of a real repeated-call loop that only escaped
    # via 5 wasted LLM attempts.
    _repeatedCallStage: Optional[str]

    pendingAction: Optional[PendingAction]
    archivedPendingActions: List[PendingAction]
    clarifyAttempts: int

    toolResults: Dict[str, Any]
    # NOTE: there is deliberately no persisted "offered candidates" field
    # here (a prior `lastOfferedCandidates` was declared but never actually
    # written anywhere — dead state, removed in the 2026-08 structured-
    # interaction fix). Offered candidates are always recomputed fresh from
    # toolResults at validation time (see graph.py's
    # _compute_offered_candidates) rather than persisted-then-trusted:
    # since ask_customer_node's pre-interrupt code re-executes from the top
    # on every resume anyway (LangGraph's interrupt() semantics), a fresh
    # recompute is already required for the interrupting pass and is
    # strictly safer than a snapshot that could drift from toolResults.

    a2uiProposal: Optional[List[Dict[str, Any]]]
    a2uiComponents: List[Dict[str, Any]]
    a2uiOrigin: Literal[
        "AGENT_PROPOSED", "DETERMINISTIC_FALLBACK", "MANDATORY_DETERMINISTIC"
    ]
    uiState: Dict[str, Any]
    status: RunStatus
    error: Optional[str]
