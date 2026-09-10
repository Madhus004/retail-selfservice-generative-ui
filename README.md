# Uni — Retail Self-Service Generative UI

Uni is a support assistant for a fictional retail brand ("Unicorn"). A customer chats in
natural language; the backend reasons over mock order data and policy docs, then responds
with both a message and a small set of structured UI components — never free-form
HTML/Markdown — that the frontend renders as a dynamic support canvas.

## Repository layout

Two independently-run services, talked to over plain HTTP — no monorepo tooling, no shared
build step.

- `agent/` — Python/FastAPI backend running a LangGraph agent.
- `frontend/` — Next.js 16 + React 19 chat UI and canvas.

## Running it

**Backend** (from repo root, using the `.venv` at repo root):
```bash
.venv/Scripts/activate        # Windows
pip install -r agent/requirements.txt
cd agent
uvicorn main:app --reload     # http://127.0.0.1:8000
```
Needs `agent/.env` with `OPENAI_API_KEY` (optional — without one, the agent runs on
deterministic rule-based fallbacks instead of the LLM).

**Frontend**:
```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
```
Needs `frontend/.env.local` with `OPENAI_API_KEY` (used only by the CopilotKit chat runtime,
separate from the agent's own key).

Run both together during development.

## Two engines, one app

The frontend can drive either of two backend engines, selectable via a dev-only toggle
(`NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE=true`). Both are live, working systems — the toggle exists
so they can be compared side by side against the same running app.

### V1 — the original fixed pipeline

A linear six-node LangGraph `StateGraph` (`agent/graph.py`): classify intent → load order
data → retrieve policy text → generate a customer-facing explanation → plan a UI response →
assemble the final state. Handles two scenarios: "where is my order" and wrong-delivery
claims. Every node has a non-LLM fallback, so the app is fully functional with no API key.

**Example: "Where is my order?"**

1. The customer types *"Where is my order?"* with no order number.
2. `detect_intent_node` classifies this as `WHERE_IS_MY_ORDER` with no order number extracted.
3. `load_data_node` calls `get_recent_orders` — since no order was named, it loads the
   customer's full recent-order list rather than one order's detail.
4. `generate_explanation_node` writes a short customer-facing message, and `plan_a2ui_node`
   picks the `orderSelection` component, listing each recent order as a card.
5. **Response the customer sees**: a message plus a list of order cards (order number,
   status, promise state).
6. **Follow-up**: the customer clicks one card, say order `U-1002`. The frontend sends a new
   turn naming that order number.
7. `detect_intent_node` now extracts `U-1002` via its order-number regex and classifies the
   turn the same way, but with a specific order in hand.
8. `load_data_node` calls `get_order_promise_dashboard("U-1002")` instead — packages,
   tracking events, the delivery promise, and any delivery proof or service-recovery offer
   for that one order.
9. `plan_a2ui_node` now picks `promiseDashboard` (plus `deliveryProof`/`serviceRecovery` if the
   data warrants it).
10. **Response the customer sees**: the full tracking/promise dashboard for `U-1002` — the
    direct result of the card they clicked in step 6.

### V3 — the current architecture

A bounded, autonomous LangGraph agent (`agent/v3/**`) that reasons in a loop over tools
rather than following a fixed node sequence. Built around LangGraph's own `messages` history
(instead of hand-rolled conversation-summary state) and an ordered tool-call log, with
SQLite-backed checkpointing, idempotency, and confirmation for sensitive actions. Supports
four capabilities:

| Capability | What it does |
|---|---|
| Order Status | Look up recent orders, tracking, delivery promises |
| General Assistance | Policy-grounded Q&A for anything outside the transactional flows |
| Cancellation | Cancel one or more items on an eligible order, with confirm-before-execute |
| Returns | Return eligible items with a reason and method, with confirm-before-execute |

UI responses are an ordered list of fine-grained components (a status pill, an item picker,
a confirmation card, ...) rather than V1's one-screen-per-turn model, giving the agent more
expressive range while still only ever choosing from a fixed, server-validated catalog.

**Example: "I'd like to return something."**

1. The customer types *"I'd like to return something."* with no order named.
2. `classify_capability_node` classifies the turn as `RETURNS`; `enforce_capability_switch_node`
   resets any scratch state left over from a previous capability.
3. `agent_reason_node` sees no order named and no eligible-orders list fetched yet, so it
   decides to call `get_return_eligible_orders_tool`.
4. `execute_tool_node` runs it and returns only the customer's return-eligible orders (i.e.
   delivered and still inside the return window) — say `U-1001` and `U-1002`.
5. The loop runs again: with more than one eligible order and none selected,
   `agent_reason_node` returns an `ASK_CUSTOMER` decision expecting an `ORDER_SELECTED`
   response, proposing an `OrderListPicker`.
6. **Response the customer sees**: a message asking which order, plus a picker listing
   `U-1001` and `U-1002` as cards.
7. **Follow-up**: the customer clicks "Order U-1001". The frontend resumes the same
   LangGraph thread with a structured `ORDER_SELECTED` payload — validated against the exact
   orders offered in step 6, never re-interpreted as free text.
8. `agent_reason_node` now calls `get_return_eligible_items_tool("U-1001")`; with more than
   one returnable item, it asks which items (`ItemPicker`), then — after that's answered —
   asks for a reason (`ReturnReasonPrompt`), then a return method if more than one is
   available (`ReturnMethodPrompt`). Each of these is its own ask/resume round-trip, the same
   structured-selection pattern as step 7.
9. Once order, items, reason, and method are all resolved, `agent_reason_node` proposes the
   sensitive action: it builds a preview (order, items, estimated refund) and interrupts with
   `CONFIRM_ACTION`, rendering a `ConfirmationCard`.
10. **Follow-up**: the customer taps "Confirm". Only now does `create_return_tool` actually
    execute — guarded by an idempotency check so a duplicate confirmation can never submit the
    same return twice.
11. **Response the customer sees**: a final confirmation message with the return ID and
    estimated refund — the end of a five-round-trip conversation that started with one vague
    sentence.
