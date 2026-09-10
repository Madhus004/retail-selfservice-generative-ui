// frontend/lib/agent-api-v2.ts
//
// V2's own request-layer client — a sibling to agent-api.ts (V1), never a
// replacement. V1's client stays byte-for-byte untouched; talks to
// agent/v2/router.py's POST /v2/agent/chat, a genuinely different protocol
// (multi-turn, threadId-scoped, structured resumes for button clicks) from
// V1's stateless single-call /agent/chat — but the response's uiState is
// still the same {uiMode, assistantMessage, canvasData, a2ui} shape the
// rendering layer already knows how to walk.

import type { PageContext } from "@/lib/page-context";
import { AGENT_API_BASE_URL } from "@/lib/agent-api";

// V2's own component catalog (agent/v2/capabilities/*.py's
// allowed_agent_a2ui/mandatory_a2ui + agent/v2/a2ui.py's
// _MANDATORY_UI_TYPES). A few names are deliberately reused verbatim from
// V1 (orderSelection, welcome, cancellationConfirmed, claimSubmitted); the
// rest are new, V2-only names — kept as an explicit union here (not
// `string`) per this repo's A2UI hard constraint: every renderable type is
// enumerated, never free-form.
export type V2ComponentType =
  | "welcome"
  | "orderSelection"
  | "orderStatus"
  | "deliveryTimeline"
  | "deliveryProof"
  | "serviceRecovery"
  | "cancellationOrderSelection"
  | "cancellationItemSelection"
  | "cancellationConfirmationPending"
  | "cancellationConfirmed"
  | "returnItemSelection"
  | "returnReasonPrompt"
  | "returnMethodPrompt"
  | "returnConfirmationPending"
  | "returnSubmitted"
  | "wrongDeliveryClaimForm"
  | "claimConfirmationPending"
  | "claimSubmitted"
  | "suggestedReplies";

// The full structured-selection vocabulary (2026-08 structured-interaction
// fix) — one canonical set of strings shared end to end with the backend's
// InteractionType (agent/v2/graph.py): a resume's "type", the interrupt's
// "expectedInteractionType", and the trace's "interactionType" all use the
// same values, so validating a resume is an equality check, not inference.
export type StructuredInteractionType =
  | "ORDER_SELECTED"
  | "ITEM_SELECTED"
  | "REASON_SELECTED"
  | "RETURN_METHOD_SELECTED";

export type StructuredSelectionResume =
  | { type: "ORDER_SELECTED"; capability: string; payload: { orderNumber: string } }
  | {
      type: "ITEM_SELECTED";
      capability: string;
      payload: { selections: { orderLineId: string; quantity: number }[] };
    }
  | { type: "REASON_SELECTED"; capability: string; payload: { reason: string } }
  | { type: "RETURN_METHOD_SELECTED"; capability: string; payload: { method: string } };

export type A2UIComponentV2 = {
  type: V2ComponentType;
  props?: Record<string, unknown>;
  dataKey?: string | null;
};

export type AgentUIStateV2 = {
  uiMode: string;
  assistantMessage: string;
  canvasData?: Record<string, unknown>;
  a2ui: A2UIComponentV2[];
  // Contextual next-step chips attached to THIS turn (2026-08 fix) — same
  // shape/precedent as V1's own uiState.suggestedReplies. Only set on some
  // turns (e.g. UNSUPPORTED, or a plain informational ORDER_STATUS
  // answer), never a permanent menu.
  suggestedReplies?: string[];
};

export type AgentChatResponseV2 = {
  message: string;
  capability: string;
  orderNumber?: string | null;
  uiState: AgentUIStateV2;
  status:
    | "FINAL"
    | "INTERRUPTED_ASK"
    | "INTERRUPTED_CONFIRM"
    | "UNSUPPORTED"
    | "ERROR";
  threadId: string;
  runId: string;
};

async function postV2(
  body: Record<string, unknown>
): Promise<AgentChatResponseV2> {
  const response = await fetch(`${AGENT_API_BASE_URL}/v2/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();

    throw new Error(
      `V2 agent API request failed with status ${response.status}: ${errorText}`
    );
  }

  return response.json();
}

// A fresh or continuing free-text turn. threadId is null/undefined for the
// very first message of a conversation — the backend mints one and echoes
// it back, and every subsequent call on this conversation must pass it.
export async function sendAgentMessageV2(
  message: string,
  threadId?: string | null,
  pageContext?: PageContext | null
): Promise<AgentChatResponseV2> {
  return postV2({
    message,
    threadId: threadId ?? undefined,
    pageContext: pageContext ?? undefined,
  });
}

export type ConfirmationResume = {
  confirmation: { actionId: string; actionType: string; accepted: boolean };
};

// A structured, code-generated resume — an order/item/reason/method
// selection click or a real Confirm/Decline button. Every caller of this
// function must be a genuine UI interaction, never a parsed chat message
// (plan section 18a, correction 1: free text can never construct or
// satisfy a confirmation — this is enforced by the type here accepting
// only these two shapes, never a plain string).
export async function resumeAgentMessageV2(
  threadId: string,
  resume: StructuredSelectionResume | ConfirmationResume
): Promise<AgentChatResponseV2> {
  return postV2({ threadId, resume });
}
