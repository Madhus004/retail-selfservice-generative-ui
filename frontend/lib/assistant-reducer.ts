// frontend/lib/assistant-reducer.ts

import type { A2UIComponent, AgentUIMode } from "@/lib/agent-api";
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
      uiMode: AgentUIMode;
      a2ui: A2UIComponent[];
      canvasData: {
        orders?: OrderScenario[];
        selectedOrder?: OrderScenario | null;
        claimResult?: ClaimSubmissionResult | null;
        eligibleOrders?: CancellationEligibleOrder[];
        cancellationResult?: CancellationResult | null;
      };
      suggestedReplies?: string[];
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
