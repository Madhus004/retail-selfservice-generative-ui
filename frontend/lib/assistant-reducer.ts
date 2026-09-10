// frontend/lib/assistant-reducer.ts

import type { A2UIComponent, AgentUIMode } from "@/lib/agent-api";
import type { A2UIComponentV2, V2ComponentType } from "@/lib/agent-api-v2";
import type { A2UIComponentV3, V3ComponentType } from "@/lib/agent-api-v3";
import type {
  CancellationEligibleOrder,
  CancellationResult,
} from "@/types/cancellation";
import type { ClaimSubmissionResult, OrderScenario } from "@/types/order";

export type AssistantVisibility = "open" | "minimized";

export type TranscriptTurn =
  | {
      role: "user";
      id: string;
      text: string;
      ts: string;
    }
  | {
      role: "assistant";
      id: string;
      text: string;
      // V1 turns use AgentUIMode/A2UIComponent; V2 turns (Phase 8) use the
      // separate V2ComponentType/A2UIComponentV2 catalog; V3 turns use
      // A2UIComponentV3's fine-grained, composable catalog — a union of
      // all three, never a plain `string`, per this repo's A2UI hard
      // constraint.
      uiMode: AgentUIMode | V2ComponentType | V3ComponentType;
      a2ui: (A2UIComponent | A2UIComponentV2 | A2UIComponentV3)[];
      canvasData: {
        orders?: OrderScenario[];
        selectedOrder?: OrderScenario | null;
        claimResult?: ClaimSubmissionResult | null;
        eligibleOrders?: CancellationEligibleOrder[];
        cancellationResult?: CancellationResult | null;
        // V2-only (Phase 8) — RETURNS' returnItemSelection screen.
        returnEligibility?: Record<string, unknown> | null;
        // V2-only (2026-08 structured-interaction fix) — RETURNS' fixed
        // reason options for the returnReasonPrompt screen.
        returnReasonOptions?: string[];
        // V3-only — RETURNS' own eligible-orders list. A separate key from
        // `orders` (ORDER_STATUS's): pre-filtered to return-eligible
        // orders only, must never be conflated with the general list.
        returnEligibleOrders?: CancellationEligibleOrder[];
      };
      suggestedReplies?: string[];
      // Which engine produced this turn — decides how a click on this
      // turn's UI (e.g. selecting an order) gets sent back: V1's free-text
      // convention, V2's structured resume, or V3's (capability-free)
      // structured resume. Absent/undefined means V1, for every turn
      // built before Phase 8 existed.
      engine?: "v1" | "v2" | "v3";
      // V2/V3-only — the active capability and, when known, the currently-
      // resolved order for this turn. V2's structured resume needs a
      // "capability" field to match what the backend has active; V3's
      // resume doesn't carry one, but `capability` is still handy for
      // deciding what the turn's own click handlers should do.
      capability?: string;
      orderNumber?: string | null;
      ts: string;
    };

export type AssistantState = {
  visibility: AssistantVisibility;
  transcript: TranscriptTurn[];
  isAgentLoading: boolean;
  loadingLabel: string | null;
  loadingOrderNumber: string | null;
};

export const initialAssistantState: AssistantState = {
  visibility: "minimized",
  transcript: [],
  isAgentLoading: false,
  loadingLabel: null,
  loadingOrderNumber: null,
};

export type AssistantAction =
  | { type: "OPEN" }
  | { type: "MINIMIZE" }
  | { type: "CLOSE" }
  | {
      type: "HYDRATE";
      visibility: AssistantVisibility;
      transcript: TranscriptTurn[];
    }
  | {
      type: "SEND_MESSAGE";
      turn: TranscriptTurn;
      loadingLabel: string;
      loadingOrderNumber?: string | null;
    }
  | { type: "RECEIVE_RESPONSE"; turn: TranscriptTurn }
  | { type: "RECEIVE_ERROR"; turn: TranscriptTurn };

export function assistantReducer(
  state: AssistantState,
  action: AssistantAction
): AssistantState {
  switch (action.type) {
    case "OPEN":
      return { ...state, visibility: "open" };

    case "MINIMIZE":
      return { ...state, visibility: "minimized" };

    case "CLOSE":
      // Unlike MINIMIZE, closing ends the session: the transcript is
      // discarded so the next open starts a fresh conversation.
      return { ...initialAssistantState };

    case "HYDRATE":
      return {
        ...state,
        visibility: action.visibility,
        transcript: action.transcript,
      };

    case "SEND_MESSAGE":
      return {
        ...state,
        transcript: [...state.transcript, action.turn],
        isAgentLoading: true,
        loadingLabel: action.loadingLabel,
        loadingOrderNumber: action.loadingOrderNumber ?? null,
      };

    case "RECEIVE_RESPONSE":
    case "RECEIVE_ERROR":
      return {
        ...state,
        transcript: [...state.transcript, action.turn],
        isAgentLoading: false,
        loadingLabel: null,
        loadingOrderNumber: null,
      };

    default:
      return state;
  }
}
