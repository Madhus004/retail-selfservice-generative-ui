# agent/v3/router.py
#
# V3's own FastAPI router, mounted additively onto the existing app in
# agent/main.py — V1's and V2's routes are untouched.
#
# Phase 1 adds the first real interrupt (ORDER_STATUS's order-selection
# ask), so this now has two of V2's three router branches: a trusted
# structured resume (a click — never re-classified, a button click cannot
# contain a new goal), and free text arriving while an interrupt is
# pending. That second branch is deliberately simplified versus V2's: it
# always forwards as a plain continuation, no capability-pivot judgment
# yet — ask_customer_node's own resume handling decides whether the reply
# matches the expected structured type or falls through as free text.
# Real pivot sophistication (classify first, decide abandon-vs-continue)
# lands in Phase 2 once a second real capability exists to pivot into,
# same phasing V2 used.

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from v3.customer import DEMO_CUSTOMER_ID
from v3.graph import v3_agent_graph
from v3.observability import get_trace, get_trace_by_thread, langsmith_enabled

router = APIRouter(prefix="/v3", tags=["v3"])


@router.get("/health")
def health():
    return {"status": "ok", "engine": "v3", "langsmithEnabled": langsmith_enabled()}


@router.get("/agent/trace/{run_id}")
def agent_trace(run_id: str):
    records = get_trace(run_id)

    if not records:
        raise HTTPException(status_code=404, detail=f"No trace found for run {run_id}.")

    return {"runId": run_id, "records": records}


@router.get("/agent/thread/{thread_id}/trace")
def agent_thread_trace(thread_id: str):
    runs = get_trace_by_thread(thread_id)

    if not runs:
        raise HTTPException(status_code=404, detail=f"No trace found for thread {thread_id}.")

    return {"threadId": thread_id, "runs": runs}


class AgentChatRequestV3(BaseModel):
    message: Optional[str] = None
    pageContext: Optional[Dict[str, Any]] = None
    threadId: Optional[str] = None
    # Reserved for Phase 1+ structured resumes (order/item selection,
    # Confirm/Decline) — unused until a capability with interrupts exists.
    resume: Optional[Dict[str, Any]] = None


class AgentChatResponseV3(BaseModel):
    message: str
    capability: str
    orderNumber: Optional[str] = None
    uiState: Dict[str, Any]
    status: str
    threadId: str
    runId: str


def _pending_interrupt(config: Dict[str, Any]):
    """Read-only inspection of a thread's current checkpoint — no execution."""

    snapshot = v3_agent_graph.get_state(config)

    if not snapshot.interrupts:
        return None

    return snapshot.interrupts[0].value


def _response_from_raw_state(raw_state: Dict[str, Any], thread_id: str, run_id: str) -> AgentChatResponseV3:
    interrupt_info = raw_state.get("__interrupt__")

    if interrupt_info:
        # The graph paused this turn — ask_customer/request_confirmation
        # never "returned" on this pass, so nothing was committed to
        # uiState/status; what to show the customer lives in the
        # interrupt's own value instead.
        interrupt_value = interrupt_info[0].value
        ui_state = interrupt_value.get("uiState") or {}
        status = (
            "INTERRUPTED_CONFIRM"
            if interrupt_value.get("interruptType") == "CONFIRM_ACTION"
            else "INTERRUPTED_ASK"
        )
    else:
        ui_state = raw_state.get("uiState") or {}
        status = raw_state.get("status", "FINAL")

    # The order this turn is actually scoped to, when resolved — the
    # frontend needs this to know which order a CancellationItemPicker/
    # ReturnItemPicker screen belongs to, since canvasData's eligible-
    # orders lists are never pre-filtered to just one order.
    classification = raw_state.get("_classification") or {}

    return AgentChatResponseV3(
        message=ui_state.get("assistantMessage", ""),
        capability=raw_state.get("activeCapability", "GENERAL_ASSISTANCE"),
        orderNumber=classification.get("orderNumber"),
        uiState=ui_state,
        status=status,
        threadId=thread_id,
        runId=run_id,
    )


@router.post("/agent/chat", response_model=AgentChatResponseV3)
def v3_agent_chat(request: AgentChatRequestV3) -> AgentChatResponseV3:
    thread_id = request.threadId or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id, "run_id": run_id}}

    if request.resume is not None:
        # A structured, code-generated resume — trusted to route into the
        # interrupted node without LLM classification, but still
        # deterministically validated downstream (ask_customer_node's
        # offered-candidates check) before use.
        raw_state = v3_agent_graph.invoke(Command(resume=request.resume), config=config)
        return _response_from_raw_state(raw_state, thread_id, run_id)

    pending = _pending_interrupt(config)

    if pending is not None and request.message:
        if pending.get("interruptType") == "CONFIRM_ACTION":
            # Free text arriving during a pending confirmation is NEVER
            # authorization, regardless of content — forwarded as a
            # reminder, never as a synthesized confirmation object (same
            # invariant V2 hardened this on: only a real Confirm/Decline
            # button click ever produces a {"confirmation": {...}} resume).
            raw_state = v3_agent_graph.invoke(
                Command(resume={"__confirmationReminder__": True, "customerMessage": request.message}),
                config=config,
            )
        else:
            raw_state = v3_agent_graph.invoke(
                Command(resume={"customerReply": request.message}), config=config
            )
        return _response_from_raw_state(raw_state, thread_id, run_id)

    raw_state = v3_agent_graph.invoke(
        {
            "messages": [HumanMessage(content=request.message or "")],
            "threadId": thread_id,
            "customerId": DEMO_CUSTOMER_ID,
            "pageContext": request.pageContext,
        },
        config=config,
    )
    return _response_from_raw_state(raw_state, thread_id, run_id)
