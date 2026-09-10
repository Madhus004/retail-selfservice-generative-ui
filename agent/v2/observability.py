# agent/v2/observability.py
#
# Real per-node trace records tied to actual execution (plan section 29) —
# V1's equivalent is a hardcoded, cosmetic 8-item progress list emitted
# before the graph even runs; V2's trace reflects what genuinely happened.
#
# Privacy stance, matching the CLAUDE.md customer-vs-developer-trace
# precedent (rawState was deliberately removed from /agent/chat's
# response): tool inputs/results are stored as already-structured data
# (order numbers, quantities, tool names), never raw LLM prompt/response
# text or a full message transcript. This module never reintroduces that
# leak — it's designed this way from the start rather than needing a later
# fix.

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class TraceRecord:
    runId: str
    sessionId: Optional[str]
    ts: str
    loopIteration: int
    activeCapability: Optional[str]
    capabilityTransition: Optional[Dict[str, Any]] = None
    agentAction: Optional[str] = None  # CALL_TOOL | ASK_CUSTOMER | FINISH | CLASSIFY | SWITCH
    requestedTool: Optional[str] = None
    toolInputSummary: Optional[Dict[str, Any]] = None
    toolResultSummary: Optional[Any] = None
    model: Optional[str] = None
    promptTokens: Optional[int] = None
    completionTokens: Optional[int] = None
    latencyMs: Optional[float] = None
    interruptType: Optional[str] = None
    confirmationActionId: Optional[str] = None
    a2uiProposed: Optional[List[Dict[str, Any]]] = None
    a2uiOrigin: Optional[str] = None
    retryOrError: Optional[str] = None
    finalOutcome: Optional[str] = None

    # Structured-UI-interaction observability (2026-08 structured-
    # interaction fix) — makes a RESUME driven by a button click/selection
    # distinguishable in the trace from a free-text turn, without logging
    # the raw resume payload. interactionType is one of "ORDER_SELECTED" /
    # "ITEM_SELECTED" / "REASON_SELECTED" / "RETURN_METHOD_SELECTED" /
    # "CONFIRM_ACTION"; interactionSource is "A2UI" (a real UI interaction)
    # vs "FREE_TEXT". selectionSummary holds only small structured facts
    # (e.g. {"orderNumber": "U-1001"}) — never a full payload dump.
    interactionType: Optional[str] = None
    interactionSource: Optional[str] = None
    selectionSummary: Optional[Dict[str, Any]] = None
    validatedAgainstCandidates: Optional[bool] = None

    # Derived-fresh-from-state workflow stage (2026-08 workflow-stage fix)
    # — e.g. "WAITING_FOR_ORDER_SELECTION", "WAITING_FOR_CONFIRMATION" —
    # makes multi-turn diagnosis possible without re-deriving it from raw
    # tool results by hand. Computed the same way for every record by
    # graph.py's _compute_workflow_stage; never persisted as its own piece
    # of state, always recomputed.
    workflowStage: Optional[str] = None


# In-memory only, keyed by run_id — a server restart loses trace history,
# same documented limitation as the checkpointer/idempotency store (plan
# sections 13/21). Fine for the prototype; would need durable storage
# before any real deployment.
_TRACE_STORE: Dict[str, List[TraceRecord]] = {}


def emit(record: TraceRecord) -> None:
    _TRACE_STORE.setdefault(record.runId, []).append(record)


def get_trace(run_id: str) -> List[Dict[str, Any]]:
    return [asdict(record) for record in _TRACE_STORE.get(run_id, [])]


def get_trace_by_thread(thread_id: str) -> List[Dict[str, Any]]:
    """
    Every run that ever emitted a record for this thread, in chronological
    order, each with its own records — supports GET
    /v2/agent/thread/{thread_id}/trace so a full multi-turn conversation
    can be inspected as a whole rather than one runId at a time.

    _TRACE_STORE is keyed by runId, not threadId (sessionId on TraceRecord
    IS the threadId — see graph.py's _emit — just under a different field
    name), so this is a filter-and-group read, not a second write-path: no
    new index to keep in sync, just a query over the existing store. Fine
    at this store's current (in-memory, prototype) scale; a durable
    implementation would index by threadId at write time instead.
    """

    runs = [
        {"runId": run_id, "records": [asdict(record) for record in records]}
        for run_id, records in _TRACE_STORE.items()
        if records and records[0].sessionId == thread_id
    ]

    runs.sort(key=lambda run: run["records"][0]["ts"])

    return runs


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Stopwatch:
    """Tiny helper so node code doesn't repeat time.perf_counter() bookkeeping."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000
