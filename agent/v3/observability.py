# agent/v3/observability.py
#
# Real per-node trace records tied to actual execution — the same
# domain-specific shape V2's observability.py proved out (workflowStage,
# agentAction, tool-call summaries were what actually made every bug this
# project has hit diagnosable from a thread log alone). The only change
# here is durability: V2 kept these in an in-memory dict that a server
# restart silently erased; V3 writes them to the same SQLite file
# everything else durable lives in (see db.py).
#
# Privacy stance carried forward unchanged: tool inputs/results are stored
# as already-structured data (order numbers, quantities, tool names),
# never raw LLM prompt/response text or a full message transcript. This
# store is safe to return to the frontend's dev trace panel because of
# that discipline — never add state["messages"] (which WILL contain real
# prompt/response content) to a TraceRecord.
#
# LangSmith (already an installed dependency) is the complementary,
# LLM-call-level layer this deliberately doesn't try to replace: set
# LANGCHAIN_TRACING_V2=true, LANGCHAIN_API_KEY=..., and optionally
# LANGCHAIN_PROJECT=unicorn-v3 in agent/.env, and every ChatOpenAI call
# LangChain makes is automatically traced there — no code change needed.
# langsmith_enabled() below just lets /v3/health report whether that's on.

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from v3.db import get_connection


@dataclass
class TraceRecord:
    runId: str
    sessionId: Optional[str]
    ts: str
    loopIteration: int
    activeCapability: Optional[str]
    capabilityTransition: Optional[Dict[str, Any]] = None
    agentAction: Optional[str] = None  # CALL_TOOL | ASK_CUSTOMER | FINISH | CLASSIFY | SWITCH | ...
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
    interactionType: Optional[str] = None
    interactionSource: Optional[str] = None
    selectionSummary: Optional[Dict[str, Any]] = None
    validatedAgainstCandidates: Optional[bool] = None
    workflowStage: Optional[str] = None


def emit(record: TraceRecord) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trace_records (run_id, session_id, ts, record_json) VALUES (?, ?, ?, ?)",
            (record.runId, record.sessionId, record.ts, json.dumps(asdict(record), default=str)),
        )


def get_trace(run_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT record_json FROM trace_records WHERE run_id = ? ORDER BY id ASC", (run_id,)
        ).fetchall()

    return [json.loads(row["record_json"]) for row in rows]


def get_trace_by_thread(thread_id: str) -> List[Dict[str, Any]]:
    """
    Every run that ever emitted a record for this thread, in chronological
    order, each with its own records — mirrors V2's endpoint shape
    (GET /v3/agent/thread/{thread_id}/trace).
    """

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT run_id, record_json FROM trace_records WHERE session_id = ? ORDER BY id ASC",
            (thread_id,),
        ).fetchall()

    runs: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        runs.setdefault(row["run_id"], []).append(json.loads(row["record_json"]))

    return [
        {"runId": run_id, "records": records}
        for run_id, records in sorted(runs.items(), key=lambda item: item[1][0]["ts"])
    ]


def langsmith_enabled() -> bool:
    return os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true" and bool(os.getenv("LANGCHAIN_API_KEY"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000
