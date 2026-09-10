# agent/v2/router.py
#
# V2's own FastAPI router, mounted additively onto the existing app in
# agent/main.py. V1's routes/models in agent/main.py are not touched.
#
# Phase 2: threadId/checkpoint plumbing and the router's three-way branch
# (plan section 18a) for deciding, on every incoming request, whether it is
# a trusted structured resume, a fresh turn, or free text arriving while an
# interrupt is pending (which must be classified before deciding whether to
# forward it as a continuation or as a capability pivot).
# Phase 3: a fresh runId is minted per HTTP call (independent of threadId,
# which spans the whole conversation) so v2/observability.py's trace
# records can be correlated and retrieved via GET /v2/agent/trace/{run_id}.
#
# 2026-08 runId/threadId fix: runId is threaded through
# config["configurable"]["run_id"] on every invoke() call (fresh or
# resume) rather than through Command(update={"runId": ...}). It used to
# be a graph-state field written via Command.update on every resume —
# since every node in graph.py returns its ENTIRE state dict (not a
# partial delta), that update collided with the resumed node's own return
# also carrying runId, and LangGraph raised InvalidUpdateError ("Can
# receive only one value per step") on the runId channel. config is
# per-invocation and was confirmed (via an isolated minimal-graph
# experiment) to reach even a resumed node correctly with THIS call's
# value, never the original interrupting call's — exactly the "unique
# HTTP invocation identity" runId is supposed to be, with no checkpointed
# channel to collide on. threadId stays in graph state (business logic —
# confirmation.deterministic_action_id — genuinely reads it) but is only
# ever placed in the input dict on a fresh turn; a resume never rewrites
# it, since it's already durably in the checkpoint from turn 1.

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from v2.classifier import ClassificationContext, classify
from v2.graph import v2_agent_graph
from v2.observability import get_trace, get_trace_by_thread

router = APIRouter(prefix="/v2", tags=["v2"])


@router.get("/health")
def health():
    return {"status": "ok", "engine": "v2"}


@router.get("/agent/trace/{run_id}")
def agent_trace(run_id: str):
    """
    Dev-only trace lookup — feeds the comparison panel (Phase 9). Records
    are structured/redacted by construction (v2/observability.py never
    stores raw prompts/responses), so this is safe to expose without the
    rawState-style leak V1 deliberately closed off.
    """

    records = get_trace(run_id)

    if not records:
        raise HTTPException(status_code=404, detail=f"No trace found for run {run_id}.")

    return {"runId": run_id, "records": records}


@router.get("/agent/thread/{thread_id}/trace")
def agent_thread_trace(thread_id: str):
    """
    Every run in this conversation, in chronological order, each with its
    own records — so a full multi-turn conversation (including structured
    UI interactions, not just free-text turns) can be inspected as a
    whole, rather than one runId at a time via /agent/trace/{run_id} above
    (kept unchanged). Same privacy stance as that endpoint — records are
    structured/redacted by construction.
    """

    runs = get_trace_by_thread(thread_id)

    if not runs:
        raise HTTPException(status_code=404, detail=f"No trace found for thread {thread_id}.")

    return {"threadId": thread_id, "runs": runs}


class AgentChatRequestV2(BaseModel):
    message: Optional[str] = None
    pageContext: Optional[Dict[str, Any]] = None
    threadId: Optional[str] = None
    # Raw passthrough for structured, code-generated resumes only — an
    # order/item selection click or {"confirmation": {...}} from a real
    # Confirm/Decline button. Never constructed from free text by any code
    # path (plan section 18a, correction 1).
    resume: Optional[Dict[str, Any]] = None


class AgentChatResponseV2(BaseModel):
    message: str
    capability: str
    orderNumber: Optional[str] = None
    uiState: Dict[str, Any]
    status: str
    threadId: str
    runId: str


def _pending_interrupt(config: Dict[str, Any]):
    """
    Read-only inspection of a thread's current checkpoint — no execution.
    Returns (interrupt_value, current_state_values) if the thread is
    genuinely paused, else None. Confirmed against the installed
    langgraph==1.1.10: StateSnapshot exposes `.interrupts` directly (a
    tuple of Interrupt(value=...) objects), simpler than the
    snapshot.tasks[i].interrupts path the plan flagged as needing
    confirmation.
    """

    snapshot = v2_agent_graph.get_state(config)

    if not snapshot.interrupts:
        return None

    return snapshot.interrupts[0].value, snapshot.values


def _response_from_raw_state(
    raw_state: Dict[str, Any], thread_id: str, run_id: str
) -> AgentChatResponseV2:
    interrupt_info = raw_state.get("__interrupt__")

    if interrupt_info:
        # The graph paused this turn — ask_customer/request_confirmation
        # never "returned" on this pass, so nothing was committed to
        # uiState/status; what to show the customer lives in the
        # interrupt's own value instead (see ask_customer_node's docstring).
        interrupt_value = interrupt_info[0].value
        ui_state = interrupt_value.get("uiState") or {}
        interrupt_type = interrupt_value.get("interruptType")
        status = "INTERRUPTED_CONFIRM" if interrupt_type == "CONFIRM_ACTION" else "INTERRUPTED_ASK"
    else:
        ui_state = raw_state.get("uiState") or {}
        status = raw_state.get("status", "FINAL")

    classification = raw_state.get("_classification") or {}

    return AgentChatResponseV2(
        message=ui_state.get("assistantMessage", ""),
        capability=raw_state.get("activeCapability", "ORDER_STATUS"),
        orderNumber=classification.get("orderNumber"),
        uiState=ui_state,
        status=status,
        threadId=thread_id,
        runId=run_id,
    )


@router.post("/agent/chat", response_model=AgentChatResponseV2)
def v2_agent_chat(request: AgentChatRequestV2) -> AgentChatResponseV2:
    thread_id = request.threadId or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    # run_id lives in config, not state — see the module docstring above.
    config = {"configurable": {"thread_id": thread_id, "run_id": run_id}}

    if request.resume is not None:
        # Branch 1 (plan section 18a): a structured, code-generated resume
        # — trusted to route into the right interrupted node without LLM
        # classification (a button click cannot contain a new goal), but
        # still deterministically validated downstream before use
        # (ask_customer_node's offered-candidates check; confirmation's
        # seven-point validation from Phase 4 on). No `update=` — threadId
        # is already in the checkpoint from turn 1 and runId isn't state.
        raw_state = v2_agent_graph.invoke(Command(resume=request.resume), config=config)
        return _response_from_raw_state(raw_state, thread_id, run_id)

    pending = _pending_interrupt(config)

    if pending is not None and request.message:
        # Branch 3: free text arrived while this thread has a pending
        # interrupt — never forwarded blindly. Classify first, using the
        # pending interrupt as context, then decide how to resume.
        interrupt_value, state_values = pending

        recent_turns = [
            f"{turn['role']}: {turn['content']}"
            for turn in (state_values.get("conversationSummary") or [])
        ]
        context = ClassificationContext(
            activeCapability=state_values.get("activeCapability"),
            pendingInterruptType=interrupt_value.get("interruptType"),
            pendingQuestionSummary=interrupt_value.get("message"),
            recentTurnsSummary=recent_turns,
        )
        classification = classify(request.message, context)

        if classification.isCapabilitySwitch:
            resume_payload: Dict[str, Any] = {
                "__abandon__": True,
                "newMessage": request.message,
                "classification": classification.model_dump(),
            }
        elif interrupt_value.get("interruptType") == "CONFIRM_ACTION":
            # Not reachable until Phase 4 adds request_confirmation/a real
            # sensitive tool — kept here so the three-way branch is
            # complete and doesn't need revisiting then. Correction 1: free
            # text NEVER becomes a {"confirmation": {...}} payload.
            resume_payload = {
                "__confirmationReminder__": True,
                "customerMessage": request.message,
            }
        else:
            resume_payload = {"customerReply": request.message}

        raw_state = v2_agent_graph.invoke(Command(resume=resume_payload), config=config)
        return _response_from_raw_state(raw_state, thread_id, run_id)

    # Branch 2: free text, no pending interrupt — a normal fresh (or
    # capability-continuing, if this thread already finished a prior turn)
    # turn. threadId is set here (fresh turns only) so it's durably
    # checkpointed from this point on; runId is not part of the input dict
    # at all — it only ever lives in config.
    raw_state = v2_agent_graph.invoke(
        {
            "userMessage": request.message or "",
            "pageContext": request.pageContext,
            "threadId": thread_id,
        },
        config=config,
    )
    return _response_from_raw_state(raw_state, thread_id, run_id)
