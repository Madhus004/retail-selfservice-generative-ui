# agent/main.py

import asyncio
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from graph import agent_graph
from tools import get_order_promise_dashboard, get_recent_orders


app = FastAPI(
    title="Uni at Your Assistance Agent",
    version="0.1.0",
    description="FastAPI + LangGraph backend for Unicorn retail support.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentChatRequest(BaseModel):
    message: str


class AgentChatResponse(BaseModel):
    message: str
    intent: str
    orderNumber: Optional[str] = None
    uiState: Dict[str, Any]
    rawState: Dict[str, Any]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "uni-at-your-assistance-agent",
        "version": "0.1.0",
    }


@app.get("/customers/demo/recent-orders")
def recent_orders():
    return get_recent_orders()


@app.get("/orders/{order_number}/promise-dashboard")
def order_promise_dashboard(order_number: str):
    return get_order_promise_dashboard(order_number)


def build_agent_response(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    ui_state = raw_state.get("uiState", {})

    return {
        "message": ui_state.get(
            "assistantMessage",
            "I reviewed your request and updated the support workspace.",
        ),
        "intent": raw_state.get("intent", "UNKNOWN"),
        "orderNumber": raw_state.get("orderNumber"),
        "uiState": ui_state,
        "rawState": raw_state,
    }


@app.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(request: AgentChatRequest):
    raw_state = agent_graph.invoke({"userMessage": request.message})
    return build_agent_response(raw_state)


def sse_event(event_type: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"


@app.post("/agent/chat/stream")
async def agent_chat_stream(request: AgentChatRequest):
    """
    Demo-safe AG-UI-style streaming endpoint.

    This keeps /agent/chat as fallback, but provides a streaming event path:
    - RUN_STARTED
    - STATE_DELTA progress events
    - FINAL response with the same payload as /agent/chat
    - RUN_FINISHED
    """

    async def event_generator():
        run_id = f"run_{uuid.uuid4().hex[:10]}"

        yield sse_event(
            "RUN_STARTED",
            {
                "runId": run_id,
                "label": "Uni started reviewing your request",
                "status": "running",
            },
        )

        progress_events = [
            "Understanding customer intent",
            "Checking order and customer data",
            "Reviewing package and tracking details",
            "Comparing delivery events to original promise",
            "Retrieving applicable service policy",
            "Generating customer-facing explanation",
            "Selecting A2UI components from approved catalog",
            "Preparing support workspace",
        ]

        for label in progress_events:
            await asyncio.sleep(0.18)
            yield sse_event(
                "STATE_DELTA",
                {
                    "runId": run_id,
                    "label": label,
                    "status": "complete",
                },
            )

        try:
            raw_state = agent_graph.invoke({"userMessage": request.message})
            response = build_agent_response(raw_state)

            yield sse_event(
                "FINAL",
                {
                    "runId": run_id,
                    "response": response,
                },
            )

            yield sse_event(
                "RUN_FINISHED",
                {
                    "runId": run_id,
                    "label": "Uni finished updating the workspace",
                    "status": "complete",
                },
            )

        except Exception as exc:
            yield sse_event(
                "ERROR",
                {
                    "runId": run_id,
                    "label": "Uni could not complete the request",
                    "status": "error",
                    "error": str(exc),
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )