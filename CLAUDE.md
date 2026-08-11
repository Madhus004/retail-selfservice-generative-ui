# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo is two independently-run services with no shared build tooling:

- `agent/` — Python/FastAPI backend that runs a LangGraph agent ("Uni") for a fictional retail brand's self-service support.
- `frontend/` — Next.js 16 + React 19 app that renders the chat UI and a dynamic support "canvas" driven by the backend.

The two only talk over HTTP (`NEXT_PUBLIC_AGENT_API_BASE_URL`, default `http://127.0.0.1:8000`); there is no monorepo tool (no turborepo/nx, no root package.json).

## Commands

### Backend (`agent/`)

```bash
# from repo root, using the existing venv (.venv at repo root)
.venv/Scripts/activate        # Windows
pip install -r agent/requirements.txt

cd agent
uvicorn main:app --reload     # serves on http://127.0.0.1:8000
```

There is no lint/test command configured for the backend — no test files exist in `agent/`.

Requires a `.env` in `agent/` with `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`, default `gpt-4o-mini`). Without an API key, the graph still runs using rule-based fallbacks (see Architecture below) instead of the LLM.

### Frontend (`frontend/`)

```bash
cd frontend
npm install
npm run dev      # next dev, http://localhost:3000
npm run build
npm run start
npm run lint      # eslint
```

Requires a `.env.local` in `frontend/` with `OPENAI_API_KEY` (used by the CopilotKit runtime route, separate from the agent backend's key). No test framework is configured.

Run both servers concurrently during development: backend on :8000, frontend on :3000.

## Guardrails

- **Workflow**: for nontrivial changes, follow Explore → Plan → Code → Verify → Review → Commit. There is no CI and no test suite in this repo, so skipping Verify/Review is the main way regressions slip in silently.
- **A2UI is a hard constraint, not just a pattern**: the LLM must never be given a path to emit free-form HTML/JSX/Markdown-as-UI. Every renderable surface goes through the fixed component catalog — add new types to `ALLOWED_A2UI_COMPONENTS`/`PRIMARY_A2UI_COMPONENTS` and the planner prompt in `agent/graph.py`, give them a fallback in `build_default_a2ui_payload`, and add an explicit mapping in `frontend/components/A2UIRenderer.tsx`. Don't add an escape hatch (e.g. a "raw HTML" or "custom component" type) even as a shortcut.
- **Prefer additive changes to the graph**: don't restructure the `agent_graph` node pipeline or remove the non-LLM fallback branches (`fallback_intent_detection`, the `if not os.getenv("OPENAI_API_KEY")` branches, `build_default_a2ui_payload`) — they're what keeps the app fully functional with no API key. If a node needs new behavior, extend it rather than rewriting its control flow.
- **No deployment without explicit approval**: the repo currently has no Dockerfile/CI/hosting config. If one is ever added, treat any actual deploy/push-to-hosting step as requiring explicit user sign-off, not something to do as a natural next step after code changes.
- **No commits unless explicitly requested**: applies here like anywhere else, but worth flagging that `frontend/package-lock.json` has pre-existing uncommitted changes in this repo — don't fold unrelated changes into the same commit as a requested change.
- **Keep customer-facing output separate from developer/agent traces**: `POST /agent/chat` and `/agent/chat/stream`'s `FINAL` event both return a `rawState` field containing the *entire* internal `AgentState` (raw dashboard payloads, intermediate flags, etc.). The frontend's `AgentChatResponse` type doesn't declare it and no component reads it today — keep it that way. Never wire `rawState` into a customer-facing component, and treat it as debug-only even though it currently travels over the wire to the browser. This is distinct from `agentSteps`/`AgentProgressPanel`, which *is* intentionally customer-facing "what Uni is doing" copy, not an internal trace — don't confuse the two when deciding what's safe to show.
- **Target UX direction vs. current implementation**: the intended product is a retailer website as the primary experience, with the assistant opening as an integrated side panel that reflows the host page. The current frontend does not implement this — `app/page.tsx` renders the whole experience itself (`RetailHeader` + hero copy + a permanently-visible 30/70 `ChatPanel`/canvas split in `SupportWorkspace.tsx`), with no host retailer page, no open/close toggle, and no reflow mechanic. Don't treat `SupportWorkspace`'s fixed grid layout as the design to preserve — layout work should move toward the assistant being an overlay/panel on top of separate retailer page content, not a permanent column sharing a single grid with it.

## Architecture

### Backend: LangGraph pipeline (`agent/graph.py`)

`agent_graph` is a linear `StateGraph` (`agent/state.py` defines `AgentState`/`AgentUIState` as `TypedDict`s) with these nodes, always run in this order:

1. **`detect_intent_node`** — classifies the user message into one of `WHERE_IS_MY_ORDER`, `SELECT_ORDER`, `WRONG_DELIVERY`, `SUBMIT_WRONG_DELIVERY_CLAIM`, `UNKNOWN`, and extracts an order number (regex `U-\d{4}`). Uses an OpenAI structured-output call (`ChatOpenAI.with_structured_output`) when `OPENAI_API_KEY` is set, otherwise falls back to `fallback_intent_detection` (keyword/regex rules). Any LLM exception also falls back to the rules.
2. **`load_data_node`** — loads mock order/tracking data via `tools.get_recent_orders` / `tools.get_order_promise_dashboard` based on intent.
3. **`retrieve_policy_node`** — a lightweight "RAG" step: `tools.retrieve_policy_context` just selects and concatenates markdown files from `agent/data/policies/` based on promise result / reason code / issue type. No embeddings or vector store.
4. **`generate_explanation_node`** — LLM call that writes the customer-facing message, constrained by a system prompt that forbids mentioning internal systems (RAG, LangGraph, A2UI, policy files, loyalty tier, confidence scores) or inventing outcomes not present in the data. Skipped if no API key.
5. **`plan_a2ui_node`** — a second LLM call (the "A2UI planner") that chooses which UI components to render from a fixed, allow-listed catalog (see below). Output is validated by `validate_a2ui_components`, which drops any component type outside `ALLOWED_A2UI_COMPONENTS` and falls back to `build_default_a2ui_payload` (deterministic per-intent defaults) if the LLM's list is empty or lacks a "primary" component.
6. **`build_ui_state_node`** — assembles the final `uiState` (mode, assistant message, `canvasData`, `agentSteps` for the progress UI, and the `a2ui` component list) that both HTTP endpoints return.

Any node can set `state["error"]`; downstream nodes short-circuit and `build_ui_state_node` renders a generic error/welcome state instead.

**A2UI protocol**: the backend never returns HTML/JSX — only a small declarative list of `{type, props}` objects chosen from a fixed catalog (`welcome`, `orderSelection`, `promiseDashboard`, `deliveryProof`, `serviceRecovery`, `wrongDeliveryClaim`, `claimSubmitted`). `props` are meant to stay small/declarative (`dataKey` references into `canvasData`, not embedded payloads). This validated-catalog approach is intentional — when adding a new UI capability, add the type to `ALLOWED_A2UI_COMPONENTS`/`PRIMARY_A2UI_COMPONENTS` in `graph.py`, teach the planner's system prompt about it, and add a fallback branch in `build_default_a2ui_payload`, all in `agent/graph.py`, and then map it to a real component in `frontend/components/A2UIRenderer.tsx`.

**Data**: `agent/data/mock_orders.py` (`MOCK_CUSTOMER`, `MOCK_ORDERS`) is the sole data source — there is no real database. `agent/tools.py` reshapes it into recent-orders lists and per-order "promise dashboards" (packages, tracking events, delivery promises, delivery proofs, service recovery actions).

### Backend: API surface (`agent/main.py`)

- `GET /health`
- `GET /customers/demo/recent-orders`, `GET /orders/{order_number}/promise-dashboard` — direct mock-data reads, bypass the graph.
- `POST /agent/chat` — synchronous: runs `agent_graph.invoke(...)` and returns `{message, intent, orderNumber, uiState, rawState}`.
- `POST /agent/chat/stream` — AG-UI-style SSE endpoint used by the frontend. Emits synthetic `RUN_STARTED` and a hardcoded sequence of `STATE_DELTA` "progress" events (these are cosmetic/demo-only — they do not reflect the graph's actual node execution), then runs the graph and emits `FINAL` (same payload shape as `/agent/chat`) and `RUN_FINISHED`, or `ERROR` on exception.

### Frontend

- `app/page.tsx` (`Home`) owns all top-level UI state (canvas mode, `a2uiComponents`, selected order, streamed progress steps, claim result) and maps backend response shapes (`BackendRecentOrder`, `BackendDashboard`) into frontend view types (`OrderScenario`, etc. in `types/order.ts`).
- Two ways a chat request reaches the backend, both in `lib/agent-api.ts`: `sendAgentMessage` (plain POST) and `streamAgentMessage` (SSE parsing over `/agent/chat/stream`, falling back to `sendAgentMessage` if the stream yields no `FINAL` event). `page.tsx` uses the streaming path by default.
- CopilotKit is wired in as the chat entry point: `useCopilotAction("askUni", ...)` in `page.tsx` forwards the user's free-text message straight into `runStreamingAgentRequest`, i.e. CopilotKit is a thin conversational shell around the same LangGraph backend — it does not do its own intent handling. `app/api/copilotkit/route.ts` is CopilotKit's own runtime endpoint (separate `OPENAI_API_KEY` usage) and is not on the Uni agent's request path.
- `components/A2UIRenderer.tsx` interprets the backend's `a2ui` component list: it finds the first "primary" component type and dispatches to one hardcoded canvas component (`WelcomeCanvas`, `OrderSelectionCanvas`, `PromiseDashboardCanvas`, `WrongDeliveryClaimCanvas`, `ClaimSubmittedCanvas`). `deliveryProof`/`serviceRecovery` are supplemental component types folded into `PromiseDashboardCanvas` rather than rendered standalone. If you add a new primary A2UI type on the backend, add both the type and its canvas mapping here.
- `lib/mock-orders.ts` is legacy/unused fixture data from before the FastAPI backend existed — no component currently imports it. Live mock data comes from the backend (`agent/data/mock_orders.py`).
- Path alias `@/*` maps to `frontend/*` (see `tsconfig.json`).

## Frontend-specific caveat

`frontend/AGENTS.md` warns that this app pins a pre-release Next.js (`16.2.6`) with breaking API/convention changes from what training data assumes. Before writing Next.js code in `frontend/`, check `frontend/node_modules/next/dist/docs/` for the current APIs/conventions rather than relying on prior Next.js knowledge, and watch for deprecation notices.
