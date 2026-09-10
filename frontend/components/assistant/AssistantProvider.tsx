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
import type { AgentChatResponse, AgentUIMode, StreamedAgentEvent } from "@/lib/agent-api";
import {
  resumeAgentMessageV2,
  sendAgentMessageV2,
  type AgentChatResponseV2,
  type ConfirmationResume,
  type StructuredSelectionResume,
  type V2ComponentType,
} from "@/lib/agent-api-v2";
import {
  resumeAgentMessageV3,
  sendAgentMessageV3,
  type AgentChatResponseV3,
  type ConfirmationResumeV3,
  type StructuredSelectionResumeV3,
  type V3ComponentType,
} from "@/lib/agent-api-v3";
import {
  assistantReducer,
  initialAssistantState,
  type AssistantVisibility,
  type TranscriptTurn,
} from "@/lib/assistant-reducer";
import { loadAssistantSession, saveAssistantSession } from "@/lib/assistant-session";
import { getEnginePreference } from "@/components/assistant/EngineToggle";
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
  CancellationResult,
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

// V2 reuses tools.submit_order_cancellation directly (plan section 5) — its
// result dict is byte-for-byte the same shape V1's REST endpoint already
// returns as CancellationResult, so this is a type assertion, not a
// reshape.
function normalizeCancellationResult(
  result: Record<string, unknown>
): CancellationResult {
  return result as unknown as CancellationResult;
}

// V2's submit_wrong_delivery_claim doesn't return submittedAt (plan section
// 9 — new, side-effect-free code, not a fork of anything V1 has), so this
// backfills it rather than widening ClaimSubmissionResult for one missing
// field V2 has no real value for.
function normalizeClaimResult(
  result: Record<string, unknown>
): ClaimSubmissionResult {
  return {
    claimId: String(result.claimId ?? ""),
    orderNumber: String(result.orderNumber ?? ""),
    status: (result.status as ClaimSubmissionResult["status"]) ?? "submitted",
    submittedAt: String(result.submittedAt ?? nowIso()),
    slaMessage: String(result.slaMessage ?? ""),
  };
}

function buildAssistantTurnV2(
  response: AgentChatResponseV2,
  fallbackSelectedOrder: OrderScenario | null
): TranscriptTurn {
  const uiMode = response.uiState.uiMode;
  const canvasDataRaw = response.uiState.canvasData ?? {};

  let orders: OrderScenario[] | undefined;
  let selectedOrder: OrderScenario | null | undefined;
  let cancellationResult: CancellationResult | null | undefined;
  let claimResult: ClaimSubmissionResult | null | undefined;
  let returnEligibility: Record<string, unknown> | null | undefined;
  let eligibleOrders: CancellationEligibleOrder[] | undefined;
  let returnReasonOptions: string[] | undefined;

  if (uiMode === "orderSelection") {
    orders = (
      (canvasDataRaw.orders as BackendRecentOrder[] | undefined) ?? []
    ).map(mapRecentOrderToScenario);
  }

  if (uiMode === "orderStatus") {
    const dashboard = canvasDataRaw.selectedOrder as BackendDashboard | undefined;

    selectedOrder =
      dashboard && Object.keys(dashboard).length > 0
        ? { ...mapDashboardToScenario(dashboard), customerSummary: response.message }
        : fallbackSelectedOrder;
  }

  if (uiMode === "returnItemSelection" || uiMode === "returnMethodPrompt") {
    returnEligibility =
      (canvasDataRaw.returnEligibility as Record<string, unknown> | undefined) ??
      null;
  }

  if (uiMode === "cancellationOrderSelection" || uiMode === "cancellationItemSelection") {
    eligibleOrders = (canvasDataRaw.eligibleOrders as CancellationEligibleOrder[] | undefined) ?? [];
  }

  if (uiMode === "returnReasonPrompt") {
    returnReasonOptions = (canvasDataRaw.returnReasonOptions as string[] | undefined) ?? [];
  }

  // "cancellationConfirmed"/"claimSubmitted" are the two CONFIRMED-phase
  // type strings V2 reuses verbatim from V1 (plan section 8) — reusing
  // V1's own components/canvasData keys for them, rather than routing
  // through InlineConfirmationCard, so there's exactly one implementation
  // of "what a completed cancellation/claim looks like" in this app.
  const primary = response.uiState.a2ui.find((component) => component.type === uiMode);
  const resultProps = primary?.props?.result as Record<string, unknown> | undefined;

  if (uiMode === "cancellationConfirmed" && resultProps) {
    cancellationResult = normalizeCancellationResult(resultProps);
  }

  if (uiMode === "claimSubmitted" && resultProps) {
    claimResult = normalizeClaimResult(resultProps);
  }

  const a2ui =
    response.uiState.a2ui && response.uiState.a2ui.length > 0
      ? response.uiState.a2ui
      : [{ type: "welcome" as const }];

  return {
    role: "assistant",
    id: createId(),
    text: response.message,
    // Backend uiMode is a plain string (any A2UI type it knows how to
    // build); cast to this app's typed catalog rather than widening
    // TranscriptTurn to accept arbitrary strings, per the A2UI hard
    // constraint (every renderable type is enumerated, never free-form).
    uiMode: uiMode as AgentUIMode | V2ComponentType,
    a2ui,
    engine: "v2",
    capability: response.capability,
    orderNumber: response.orderNumber,
    suggestedReplies: response.uiState.suggestedReplies,
    canvasData: {
      orders,
      selectedOrder,
      cancellationResult,
      claimResult,
      returnEligibility,
      eligibleOrders,
      returnReasonOptions,
    },
    ts: nowIso(),
  };
}

// V3's uiMode is always exactly the resolved primary component's type
// string (agent/v3/ui/catalog.py's resolve_ui_mode) — a simpler, generic
// canvasData extraction than V2's needed, since V3's canvasData keys are
// already capability-neutral (eligibleOrders, returnEligibility, etc.)
// rather than requiring per-uiMode field selection.
function buildAssistantTurnV3(
  response: AgentChatResponseV3,
  fallbackSelectedOrder: OrderScenario | null
): TranscriptTurn {
  const uiMode = response.uiState.uiMode;
  const canvasDataRaw = response.uiState.canvasData ?? {};

  let orders: OrderScenario[] | undefined;
  let selectedOrder: OrderScenario | null | undefined;
  let eligibleOrders: CancellationEligibleOrder[] | undefined;
  let returnEligibleOrders: CancellationEligibleOrder[] | undefined;
  let returnEligibility: Record<string, unknown> | null | undefined;
  let returnReasonOptions: string[] | undefined;

  if (uiMode === "OrderListPicker") {
    orders = ((canvasDataRaw.orders as BackendRecentOrder[] | undefined) ?? []).map(
      mapRecentOrderToScenario
    );
    returnEligibleOrders =
      (canvasDataRaw.returnEligibleOrders as CancellationEligibleOrder[] | undefined) ?? [];
  }

  if (uiMode === "OrderSummaryCard") {
    const dashboard = canvasDataRaw.selectedOrder as BackendDashboard | undefined;

    selectedOrder =
      dashboard && Object.keys(dashboard).length > 0
        ? { ...mapDashboardToScenario(dashboard), customerSummary: response.message }
        : fallbackSelectedOrder;
  }

  if (uiMode === "CancellationOrderPicker" || uiMode === "CancellationItemPicker") {
    eligibleOrders = (canvasDataRaw.eligibleOrders as CancellationEligibleOrder[] | undefined) ?? [];
  }

  if (uiMode === "ReturnItemPicker" || uiMode === "ReturnMethodPrompt") {
    returnEligibility =
      (canvasDataRaw.returnEligibility as Record<string, unknown> | undefined) ?? null;
  }

  if (uiMode === "ReturnReasonPrompt") {
    returnReasonOptions = (canvasDataRaw.returnReasonOptions as string[] | undefined) ?? [];
  }

  const a2ui =
    response.uiState.a2ui && response.uiState.a2ui.length > 0
      ? response.uiState.a2ui
      : [{ type: "Welcome" as const }];

  return {
    role: "assistant",
    id: createId(),
    text: response.message,
    uiMode: uiMode as V3ComponentType,
    a2ui,
    engine: "v3",
    capability: response.capability,
    orderNumber: response.orderNumber,
    canvasData: {
      orders,
      selectedOrder,
      eligibleOrders,
      returnEligibleOrders,
      returnEligibility,
      returnReasonOptions,
    },
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
  // V2-only: sends a structured, code-generated resume (order/item/reason/
  // method selection, Confirm/Decline) on the current V2 thread. Typed to
  // only accept the two resume shapes the backend actually validates
  // (2026-08 structured-interaction fix) — never a plain string — so a
  // structured selection can't accidentally be built from free text at
  // the call site. userFacingLabel is shown as the synthetic "user said"
  // bubble in the transcript.
  resumeV2: (
    resume: StructuredSelectionResume | ConfirmationResume,
    userFacingLabel: string
  ) => Promise<string>;
  // V3-only: same shape as resumeV2, but for V3's own thread/resume
  // vocabulary (no "capability" field on the resume payload — see
  // agent-api-v3.ts).
  resumeV3: (
    resume: StructuredSelectionResumeV3 | ConfirmationResumeV3,
    userFacingLabel: string
  ) => Promise<string>;
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
  // V2's own conversation thread id (plan section 19) — persists across
  // turns within one open chat session, reset on close() so the next chat
  // starts a fresh V2 conversation. Kept out of assistant-session.ts's
  // persisted schema deliberately: V2 is dev/comparison-only for now
  // (behind the engine toggle), not part of the real session contract.
  const v2ThreadIdRef = useRef<string | null>(null);
  // V3's own conversation thread id — same lifecycle/rationale as
  // v2ThreadIdRef, kept separate so switching the engine toggle mid-session
  // can never mix a V2 thread's state with a V3 one.
  const v3ThreadIdRef = useRef<string | null>(null);
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

  const beginTurn = useCallback(
    (
      userFacingText: string,
      options: { loadingLabel: string; loadingOrderNumber?: string }
    ) => {
      const userTurn: TranscriptTurn = {
        role: "user",
        id: createId(),
        text: userFacingText,
        ts: nowIso(),
      };

      dispatch({
        type: "SEND_MESSAGE",
        turn: userTurn,
        loadingLabel: options.loadingLabel,
        loadingOrderNumber: options.loadingOrderNumber ?? null,
      });
    },
    []
  );

  // V2's own request path (Phase 8) — no cosmetic per-node progress stream
  // to consume (that's V1's /agent/chat/stream-only convenience; V2's real
  // observability lives in GET /v2/agent/trace/{runId} instead, not wired
  // into this panel), so this is a single request/response round trip
  // rather than streamAgentMessage's SSE handling.
  const runRequestV2 = useCallback(
    async (
      invoke: () => Promise<AgentChatResponseV2>,
      userFacingText: string,
      options: { loadingLabel: string; fallbackOrder?: OrderScenario }
    ) => {
      beginTurn(userFacingText, { loadingLabel: options.loadingLabel });
      setAgentTrace([]);

      try {
        const response = await invoke();
        v2ThreadIdRef.current = response.threadId;

        const assistantTurn = buildAssistantTurnV2(
          response,
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
        return response.message;
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
            engine: "v2",
            ts: nowIso(),
          },
        });

        return errorText;
      }
    },
    [beginTurn]
  );

  const resumeV2 = useCallback(
    (resume: StructuredSelectionResume | ConfirmationResume, userFacingLabel: string) => {
      const threadId = v2ThreadIdRef.current;

      if (!threadId) {
        // A structured resume is only ever offered on a turn that already
        // has a V2 thread — reaching here without one would be a
        // rendering bug, not a real runtime state. Fail soft rather than
        // throw out of a click handler.
        return Promise.resolve(
          "That action is no longer available — please send a new message."
        );
      }

      return runRequestV2(
        () => resumeAgentMessageV2(threadId, resume),
        userFacingLabel,
        { loadingLabel: "Uni is looking into this..." }
      );
    },
    [runRequestV2]
  );

  // V3's own request path — same single request/response round trip shape
  // as runRequestV2 (no cosmetic progress stream to consume).
  const runRequestV3 = useCallback(
    async (
      invoke: () => Promise<AgentChatResponseV3>,
      userFacingText: string,
      options: { loadingLabel: string; fallbackOrder?: OrderScenario }
    ) => {
      beginTurn(userFacingText, { loadingLabel: options.loadingLabel });
      setAgentTrace([]);

      try {
        const response = await invoke();
        v3ThreadIdRef.current = response.threadId;

        const assistantTurn = buildAssistantTurnV3(
          response,
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
        return response.message;
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
            uiMode: "Welcome",
            a2ui: [{ type: "Welcome", props: { error: true } }],
            canvasData: {},
            engine: "v3",
            ts: nowIso(),
          },
        });

        return errorText;
      }
    },
    [beginTurn]
  );

  const resumeV3 = useCallback(
    (resume: StructuredSelectionResumeV3 | ConfirmationResumeV3, userFacingLabel: string) => {
      const threadId = v3ThreadIdRef.current;

      if (!threadId) {
        return Promise.resolve(
          "That action is no longer available — please send a new message."
        );
      }

      return runRequestV3(
        () => resumeAgentMessageV3(threadId, resume),
        userFacingLabel,
        { loadingLabel: "Uni is looking into this..." }
      );
    },
    [runRequestV3]
  );

  const runRequest = useCallback(
    async (
      message: string,
      options: {
        loadingLabel: string;
        loadingOrderNumber?: string;
        fallbackOrder?: OrderScenario;
      }
    ) => {
      // Read fresh on every call (not cached at mount) so flipping
      // EngineToggle takes effect on the very next message, no dev-server
      // restart or reload needed (plan section 27).
      if (getEnginePreference() === "v2") {
        return runRequestV2(
          () => sendAgentMessageV2(message, v2ThreadIdRef.current, pageContext),
          message,
          options
        );
      }

      if (getEnginePreference() === "v3") {
        return runRequestV3(
          () => sendAgentMessageV3(message, v3ThreadIdRef.current, pageContext),
          message,
          options
        );
      }

      beginTurn(message, {
        loadingLabel: options.loadingLabel,
        loadingOrderNumber: options.loadingOrderNumber,
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
    [pageContext, beginTurn, runRequestV2, runRequestV3]
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
        v2ThreadIdRef.current = null;
        v3ThreadIdRef.current = null;
        dispatch({ type: "CLOSE" });
      },

      resumeV2,
      resumeV3,

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
    [state, runRequest, agentTrace, resumeV2, resumeV3]
  );

  return (
    <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>
  );
}
