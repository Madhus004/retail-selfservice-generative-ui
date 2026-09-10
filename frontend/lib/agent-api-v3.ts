// frontend/lib/agent-api-v3.ts
//
// V3's own request-layer client — a sibling to agent-api.ts (V1) and
// agent-api-v2.ts (V2), never a replacement for either. Talks to
// agent/v3/router.py's POST /v3/agent/chat. Protocol shape is structurally
// identical to V2's (same {message, threadId, resume} request envelope,
// same {message, capability, uiState, status, threadId, runId} response
// envelope, same ORDER_SELECTED/ITEM_SELECTED/REASON_SELECTED/
// RETURN_METHOD_SELECTED + confirmation resume vocabulary) — the one
// protocol difference is that V3's resume payloads never carry a
// "capability" field (agent/v3/graph.py's ask_customer_node doesn't
// validate one), so StructuredSelectionResumeV3 is narrower than V2's
// StructuredSelectionResume.

import type { PageContext } from "@/lib/page-context";
import { AGENT_API_BASE_URL } from "@/lib/agent-api";

// V3's fine-grained, composable A2UI catalog (agent/v3/ui/catalog.py) —
// PascalCase primitives, one turn = an ordered list of these rather than
// one whole-screen type. Kept as an explicit union (not `string`) per this
// repo's A2UI hard constraint: every renderable type is enumerated, never
// free-form.
export type V3ComponentType =
  | "Welcome"
  | "OrderListPicker"
  | "OrderSummaryCard"
  | "StatusPill"
  | "TrackingTimeline"
  | "DeliveryProofCard"
  | "ServiceRecoveryBanner"
  | "SuggestedActions"
  | "CancellationOrderPicker"
  | "CancellationItemPicker"
  | "ConfirmationCard"
  | "ReturnItemPicker"
  | "ReturnReasonPrompt"
  | "ReturnMethodPrompt";

export type StructuredInteractionTypeV3 =
  | "ORDER_SELECTED"
  | "ITEM_SELECTED"
  | "REASON_SELECTED"
  | "RETURN_METHOD_SELECTED";

export type StructuredSelectionResumeV3 =
  | { type: "ORDER_SELECTED"; payload: { orderNumber: string } }
  | {
      type: "ITEM_SELECTED";
      payload: { selections: { orderLineId: string; quantity: number }[] };
    }
  | { type: "REASON_SELECTED"; payload: { reason: string } }
  | { type: "RETURN_METHOD_SELECTED"; payload: { method: string } };

export type ConfirmationResumeV3 = {
  confirmation: { actionId: string; actionType: string; accepted: boolean };
};

export type A2UIComponentV3 = {
  type: V3ComponentType;
  props?: Record<string, unknown>;
  dataKey?: string | null;
};

export type AgentUIStateV3 = {
  uiMode: string;
  assistantMessage: string;
  canvasData?: Record<string, unknown>;
  a2ui: A2UIComponentV3[];
};

export type AgentChatResponseV3 = {
  message: string;
  capability: string;
  orderNumber?: string | null;
  uiState: AgentUIStateV3;
  status: "FINAL" | "INTERRUPTED_ASK" | "INTERRUPTED_CONFIRM";
  threadId: string;
  runId: string;
};

async function postV3(
  body: Record<string, unknown>
): Promise<AgentChatResponseV3> {
  const response = await fetch(`${AGENT_API_BASE_URL}/v3/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();

    throw new Error(
      `V3 agent API request failed with status ${response.status}: ${errorText}`
    );
  }

  return response.json();
}

// A fresh or continuing free-text turn. threadId is null/undefined for the
// very first message of a conversation — the backend mints one and echoes
// it back, and every subsequent call on this conversation must pass it.
export async function sendAgentMessageV3(
  message: string,
  threadId?: string | null,
  pageContext?: PageContext | null
): Promise<AgentChatResponseV3> {
  return postV3({
    message,
    threadId: threadId ?? undefined,
    pageContext: pageContext ?? undefined,
  });
}

// A structured, code-generated resume — an order/item/reason/method
// selection click or a real Confirm/Decline button. Typed to only accept
// these two shapes, never a plain string, so free text can never
// construct or satisfy a confirmation.
export async function resumeAgentMessageV3(
  threadId: string,
  resume: StructuredSelectionResumeV3 | ConfirmationResumeV3
): Promise<AgentChatResponseV3> {
  return postV3({ threadId, resume });
}
