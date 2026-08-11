"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useCopilotAction } from "@copilotkit/react-core";
import { cancelOrder, sendAgentMessage, streamAgentMessage } from "@/lib/agent-api";
import type { AgentChatResponse, StreamedAgentEvent } from "@/lib/agent-api";
import {
  assistantReducer,
  initialAssistantState,
  type AssistantVisibility,
  type TranscriptTurn,
} from "@/lib/assistant-reducer";
import { loadAssistantSession, saveAssistantSession } from "@/lib/assistant-session";
import {
  mapDashboardToScenario,
  mapRecentOrderToScenario,
  type BackendDashboard,
  type BackendRecentOrder,
} from "@/lib/map-backend-order";
import type { PageContext } from "@/lib/page-context";
import type {
  CancellationEligibleOrder,
  CancellationLineSelection,
} from "@/types/cancellation";
import type {
  ClaimSubmissionResult,
  OrderScenario,
  WrongDeliveryClaimDraft,
} from "@/types/order";

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function nowIso() {
  return new Date().toISOString();
}

export type AgentTraceEntry = {
  id: string;
  type: "RUN_STARTED" | "STATE_DELTA" | "RUN_FINISHED" | "ERROR";
  label: string;
  status: string;
  ts: string;
};

function buildAssistantTurn(
  response: AgentChatResponse,
  fallbackSelectedOrder: OrderScenario | null
): TranscriptTurn {
  const uiMode = response.uiState.uiMode;
  const canvasDataRaw = response.uiState.canvasData ?? {};

  let orders: OrderScenario[] | undefined;
  let selectedOrder: OrderScenario | null | undefined;
  let eligibleOrders: CancellationEligibleOrder[] | undefined;

  if (uiMode === "orderSelection") {
    orders = ((canvasDataRaw.orders as BackendRecentOrder[] | undefined) ?? []).map(
      mapRecentOrderToScenario
    );
  }

  if (uiMode === "cancellationBuilder") {
    eligibleOrders = canvasDataRaw.eligibleOrders ?? [];
  }

  if (uiMode === "promiseDashboard" || uiMode === "wrongDeliveryClaim") {
    const dashboard = canvasDataRaw.selectedOrder as BackendDashboard | undefined;

    selectedOrder =
      dashboard && Object.keys(dashboard).length > 0
        ? { ...mapDashboardToScenario(dashboard), customerSummary: response.message }
        : fallbackSelectedOrder;
  }

  const a2ui =
    response.uiState.a2ui && response.uiState.a2ui.length > 0
      ? response.uiState.a2ui
      : [{ type: uiMode }];

  return {
    role: "assistant",
    id: createId(),
    text: response.message,
    uiMode,
    a2ui,
    canvasData: { orders, selectedOrder, eligibleOrders },
    suggestedReplies: response.uiState.suggestedReplies,
    ts: nowIso(),
  };
}

type AssistantContextValue = {
  visibility: AssistantVisibility;
  transcript: TranscriptTurn[];
  isAgentLoading: boolean;
  loadingLabel: string | null;
  loadingOrderNumber: string | null;
  agentTrace: AgentTraceEntry[];
  setPageContext: (context: PageContext | null) => void;
  open: () => void;
  minimize: () => void;
  close: () => void;
  whereIsMyOrder: () => void;
  cancelAnOrder: () => void;
  selectOrder: (order: OrderScenario) => void;
  reportWrongDelivery: (order: OrderScenario) => void;
  submitWrongDeliveryClaim: (claim: WrongDeliveryClaimDraft) => void;
  submitOrderCancellation: (
    orderNumber: string,
    lineSelections: CancellationLineSelection[],
    reason: string
  ) => void;
  backToOrders: () => void;
  backToDashboard: () => void;
  sendFreeText: (message: string) => Promise<string>;
};

export const AssistantContext = createContext<AssistantContextValue | null>(null);

export function useAssistant() {
  const context = useContext(AssistantContext);

  if (!context) {
    throw new Error("useAssistant must be used within an AssistantProvider");
  }

  return context;
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(assistantReducer, initialAssistantState);

  const lastOrdersRef = useRef<OrderScenario[]>([]);
  const lastSelectedOrderRef = useRef<OrderScenario | null>(null);
  const hasHydratedRef = useRef(false);
  const [agentTrace, setAgentTrace] = useState<AgentTraceEntry[]>([]);
  const [pageContext, setPageContext] = useState<PageContext | null>(null);

  useEffect(() => {
    const stored = loadAssistantSession();

    if (stored) {
      dispatch({
        type: "HYDRATE",
        visibility: stored.status,
        transcript: stored.transcript,
      });

      for (const turn of stored.transcript) {
        if (turn.role !== "assistant") continue;
        if (turn.canvasData.orders) lastOrdersRef.current = turn.canvasData.orders;
        if (turn.canvasData.selectedOrder) {
          lastSelectedOrderRef.current = turn.canvasData.selectedOrder;
        }
      }
    }

    hasHydratedRef.current = true;
  }, []);

  useEffect(() => {
    if (!hasHydratedRef.current) return;

    saveAssistantSession({
      status: state.visibility,
      transcript: state.transcript,
    });
  }, [state.visibility, state.transcript]);

  const runRequest = useCallback(
    async (
      message: string,
      options: {
        loadingLabel: string;
        loadingOrderNumber?: string;
        fallbackOrder?: OrderScenario;
      }
    ) => {
      const userTurn: TranscriptTurn = {
        role: "user",
        id: createId(),
        text: message,
        ts: nowIso(),
      };

      dispatch({
        type: "SEND_MESSAGE",
        turn: userTurn,
        loadingLabel: options.loadingLabel,
        loadingOrderNumber: options.loadingOrderNumber ?? null,
      });

      setAgentTrace([]);

      const recordTraceEvent = (event: StreamedAgentEvent) => {
        if (event.type === "FINAL") return;

        setAgentTrace((prev) => [
          ...prev,
          {
            id: createId(),
            type: event.type,
            label: event.label,
            status: event.status,
            ts: nowIso(),
          },
        ]);
      };

      try {
        const finalResponse =
          (await streamAgentMessage({
            message,
            pageContext,
            onEvent: recordTraceEvent,
          })) ?? (await sendAgentMessage(message, pageContext));

        const assistantTurn = buildAssistantTurn(
          finalResponse,
          options.fallbackOrder ?? lastSelectedOrderRef.current
        );

        if (assistantTurn.role === "assistant") {
          if (assistantTurn.canvasData.orders) {
            lastOrdersRef.current = assistantTurn.canvasData.orders;
          }
          if (assistantTurn.canvasData.selectedOrder) {
            lastSelectedOrderRef.current = assistantTurn.canvasData.selectedOrder;
          }
        }

        dispatch({ type: "RECEIVE_RESPONSE", turn: assistantTurn });
        return finalResponse.message;
      } catch (error) {
        console.error(error);

        const errorText =
          "I’m sorry, I couldn’t reach the Uni support agent right now. Please try again in a moment.";

        dispatch({
          type: "RECEIVE_ERROR",
          turn: {
            role: "assistant",
            id: createId(),
            text: errorText,
            uiMode: "welcome",
            a2ui: [{ type: "welcome", props: { error: true } }],
            canvasData: {},
            ts: nowIso(),
          },
        });

        return errorText;
      }
    },
    [pageContext]
  );

  useCopilotAction({
    name: "askUni",
    description:
      "Use this for any Unicorn Apparel customer support request about order tracking, delivery promise status, late delivery, weather delay, delivery proof, wrong delivery, claims, refunds, coupons, or service recovery.",
    parameters: [
      {
        name: "message",
        type: "string",
        description: "The customer's full support request.",
        required: true,
      },
    ],
    handler: async ({ message }: { message: string }) =>
      runRequest(message, { loadingLabel: "Uni is looking into this..." }),
  });

  const value = useMemo<AssistantContextValue>(
    () => ({
      visibility: state.visibility,
      transcript: state.transcript,
      isAgentLoading: state.isAgentLoading,
      loadingLabel: state.loadingLabel,
      loadingOrderNumber: state.loadingOrderNumber,
      agentTrace,
      setPageContext,

      open: () => dispatch({ type: "OPEN" }),
      minimize: () => dispatch({ type: "MINIMIZE" }),
      close: () => {
        lastOrdersRef.current = [];
        lastSelectedOrderRef.current = null;
        dispatch({ type: "CLOSE" });
      },

      whereIsMyOrder: () => {
        void runRequest("Where is my order?", {
          loadingLabel: "Checking your recent orders...",
        });
      },

      cancelAnOrder: () => {
        void runRequest("Cancel an order", {
          loadingLabel: "Checking which orders can still be cancelled...",
        });
      },

      selectOrder: (order) => {
        void runRequest(`Track ${order.orderNumber}`, {
          loadingLabel: `Reviewing order ${order.orderNumber}...`,
          loadingOrderNumber: order.orderNumber,
          fallbackOrder: order,
        });
      },

      reportWrongDelivery: (order) => {
        void runRequest(
          `My order ${order.orderNumber} says delivered but I do not see it at my address`,
          {
            loadingLabel: "Looking into your delivery issue...",
            fallbackOrder: order,
          }
        );
      },

      submitWrongDeliveryClaim: (claim) => {
        const claimId = `CLAIM-${claim.orderNumber.replace("-", "")}-${Date.now()
          .toString()
          .slice(-4)}`;

        const confirmationMessage =
          "Thanks — we submitted your wrong-delivery claim. Our service team will investigate and provide an update within 1–2 days.";

        const claimResult: ClaimSubmissionResult = {
          claimId,
          orderNumber: claim.orderNumber,
          status: "submitted",
          submittedAt: nowIso(),
          slaMessage: confirmationMessage,
        };

        dispatch({
          type: "RECEIVE_RESPONSE",
          turn: {
            role: "assistant",
            id: createId(),
            text: confirmationMessage,
            uiMode: "claimSubmitted",
            a2ui: [
              { type: "claimSubmitted", props: { dataKey: "claimResult", claimId } },
            ],
            canvasData: { claimResult },
            ts: nowIso(),
          },
        });
      },

      submitOrderCancellation: (orderNumber, lineSelections, reason) => {
        void (async () => {
          try {
            const result = await cancelOrder(orderNumber, lineSelections, reason);

            dispatch({
              type: "RECEIVE_RESPONSE",
              turn: {
                role: "assistant",
                id: createId(),
                text: `Your cancellation for order ${orderNumber} has been submitted.`,
                uiMode: "cancellationConfirmed",
                a2ui: [
                  {
                    type: "cancellationConfirmed",
                    props: { dataKey: "cancellationResult" },
                  },
                ],
                canvasData: { cancellationResult: result },
                ts: nowIso(),
              },
            });
          } catch (error) {
            console.error(error);

            dispatch({
              type: "RECEIVE_ERROR",
              turn: {
                role: "assistant",
                id: createId(),
                text: "I couldn't submit that cancellation right now. Please try again in a moment.",
                uiMode: "welcome",
                a2ui: [{ type: "welcome", props: { error: true } }],
                canvasData: {},
                ts: nowIso(),
              },
            });
          }
        })();
      },

      backToOrders: () => {
        dispatch({
          type: "RECEIVE_RESPONSE",
          turn: {
            role: "assistant",
            id: createId(),
            text: "Here are your recent orders again.",
            uiMode: "orderSelection",
            a2ui: [{ type: "orderSelection" }],
            canvasData: { orders: lastOrdersRef.current },
            ts: nowIso(),
          },
        });
      },

      backToDashboard: () => {
        if (!lastSelectedOrderRef.current) return;

        dispatch({
          type: "RECEIVE_RESPONSE",
          turn: {
            role: "assistant",
            id: createId(),
            text: `Here's order ${lastSelectedOrderRef.current.orderNumber} again.`,
            uiMode: "promiseDashboard",
            a2ui: [{ type: "promiseDashboard" }],
            canvasData: { selectedOrder: lastSelectedOrderRef.current },
            ts: nowIso(),
          },
        });
      },

      sendFreeText: (message: string) =>
        runRequest(message, { loadingLabel: "Uni is looking into this..." }),
    }),
    [state, runRequest, agentTrace]
  );

  return (
    <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>
  );
}
