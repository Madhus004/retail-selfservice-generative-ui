// frontend/lib/agent-api.ts

import type { PageContext } from "@/lib/page-context";
import type {
  CancellationEligibleOrder,
  CancellationLineSelection,
  CancellationResult,
} from "@/types/cancellation";

export type AgentUIMode =
  | "welcome"
  | "orderSelection"
  | "promiseDashboard"
  | "wrongDeliveryClaim"
  | "claimSubmitted"
  | "cancellationBuilder"
  | "cancellationConfirmed";

export type AgentStepStatus = "pending" | "running" | "complete" | "error";

export type AgentStep = {
  label: string;
  status: AgentStepStatus;
};

export type A2UIComponentType =
  | "welcome"
  | "orderSelection"
  | "promiseDashboard"
  | "deliveryProof"
  | "serviceRecovery"
  | "wrongDeliveryClaim"
  | "claimSubmitted"
  | "cancellationBuilder"
  | "cancellationConfirmed";

export type A2UIComponent = {
  type: A2UIComponentType;
  props?: Record<string, unknown>;
};

export type AgentUIState = {
  uiMode: AgentUIMode;
  assistantMessage: string;
  canvasData?: {
    customer?: unknown;
    orders?: unknown[];
    selectedOrder?: unknown;
    claimForm?: unknown;
    claimResult?: unknown;
    policy?: unknown;
    error?: string;
    eligibleOrders?: CancellationEligibleOrder[];
  };
  agentSteps?: AgentStep[];

  // Deterministic (not LLM-chosen) quick-reply suggestions for this turn
  suggestedReplies?: string[];

  // Declarative A2UI-style payload returned by LangGraph
  a2uiVersion?: string;
  a2ui?: A2UIComponent[];
};

export type AgentChatResponse = {
  message: string;
  intent:
    | "WHERE_IS_MY_ORDER"
    | "SELECT_ORDER"
    | "WRONG_DELIVERY"
    | "SUBMIT_WRONG_DELIVERY_CLAIM"
    | "ORDER_NOT_LISTED"
    | "CANCEL_ORDER"
    | "UNKNOWN";
  orderNumber?: string | null;
  uiState: AgentUIState;
};

export type StreamedAgentEvent =
  | {
      type: "RUN_STARTED";
      label: string;
      status: AgentStepStatus;
      runId?: string;
    }
  | {
      type: "STATE_DELTA";
      label: string;
      status: AgentStepStatus;
      runId?: string;
    }
  | {
      type: "FINAL";
      response: AgentChatResponse;
      runId?: string;
    }
  | {
      type: "RUN_FINISHED";
      label: string;
      status: AgentStepStatus;
      runId?: string;
    }
  | {
      type: "ERROR";
      label: string;
      status: AgentStepStatus;
      error?: string;
      runId?: string;
    };

export const AGENT_API_BASE_URL =
  process.env.NEXT_PUBLIC_AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function sendAgentMessage(
  message: string,
  pageContext?: PageContext | null
): Promise<AgentChatResponse> {
  const response = await fetch(`${AGENT_API_BASE_URL}/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message, pageContext: pageContext ?? undefined }),
  });

  if (!response.ok) {
    const errorText = await response.text();

    throw new Error(
      `Agent API request failed with status ${response.status}: ${errorText}`
    );
  }

  return response.json();
}

function parseSSEPayload(chunk: string): StreamedAgentEvent[] {
  const events: StreamedAgentEvent[] = [];
  const blocks = chunk.split("\n\n").filter(Boolean);

  for (const block of blocks) {
    const eventLine = block
      .split("\n")
      .find((line) => line.startsWith("event: "));
    const dataLine = block
      .split("\n")
      .find((line) => line.startsWith("data: "));

    if (!eventLine || !dataLine) continue;

    const type = eventLine.replace("event: ", "").trim();
    const data = JSON.parse(dataLine.replace("data: ", "").trim());

    events.push({
      type,
      ...data,
    } as StreamedAgentEvent);
  }

  return events;
}

export async function streamAgentMessage({
  message,
  pageContext,
  onEvent,
}: {
  message: string;
  pageContext?: PageContext | null;
  onEvent: (event: StreamedAgentEvent) => void;
}): Promise<AgentChatResponse | null> {
  const response = await fetch(`${AGENT_API_BASE_URL}/agent/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message, pageContext: pageContext ?? undefined }),
  });

  if (!response.ok || !response.body) {
    const errorText = await response.text();

    throw new Error(
      `Agent stream request failed with status ${response.status}: ${errorText}`
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: AgentChatResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();

    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const completeBlocks = buffer.split("\n\n");
    buffer = completeBlocks.pop() ?? "";

    const parsedEvents = parseSSEPayload(completeBlocks.join("\n\n"));

    for (const event of parsedEvents) {
      onEvent(event);

      if (event.type === "FINAL") {
        finalResponse = event.response;
      }
    }
  }

  if (buffer.trim()) {
    const parsedEvents = parseSSEPayload(buffer);

    for (const event of parsedEvents) {
      onEvent(event);

      if (event.type === "FINAL") {
        finalResponse = event.response;
      }
    }
  }

  return finalResponse;
}

// Cancellation submission is a structured form (exact order line IDs and
// quantities the wizard already validated client-side), so it goes straight
// to a dedicated REST endpoint with its own server-side re-validation,
// rather than through the chat/LLM pipeline like a free-text message would.
export async function cancelOrder(
  orderNumber: string,
  lineSelections: CancellationLineSelection[],
  reason: string
): Promise<CancellationResult> {
  const response = await fetch(
    `${AGENT_API_BASE_URL}/orders/${orderNumber}/cancellation`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ lineSelections, reason }),
    }
  );

  if (!response.ok) {
    const errorText = await response.text();

    throw new Error(
      `Cancellation request failed with status ${response.status}: ${errorText}`
    );
  }

  return response.json();
}