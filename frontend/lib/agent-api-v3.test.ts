import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  resumeAgentMessageV3,
  sendAgentMessageV3,
  type AgentChatResponseV3,
} from "@/lib/agent-api-v3";

function mockResponse(body: AgentChatResponseV3) {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

const SAMPLE_RESPONSE: AgentChatResponseV3 = {
  message: "Here's your order.",
  capability: "ORDER_STATUS",
  orderNumber: "U-1002",
  uiState: {
    uiMode: "OrderSummaryCard",
    assistantMessage: "Here's your order.",
    canvasData: {},
    a2ui: [{ type: "OrderSummaryCard" }],
  },
  status: "FINAL",
  threadId: "thread-123",
  runId: "run-456",
};

describe("agent-api-v3", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sendAgentMessageV3 posts to /v3/agent/chat with the message and omits threadId on the first turn", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    const result = await sendAgentMessageV3("Where is my order?");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/v3/agent/chat");
    expect(init?.method).toBe("POST");

    const body = JSON.parse(init?.body as string);
    expect(body).toEqual({ message: "Where is my order?", threadId: undefined, pageContext: undefined });
    expect(result).toEqual(SAMPLE_RESPONSE);
  });

  it("sendAgentMessageV3 threads a continuing threadId through", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    await sendAgentMessageV3("Why is it late?", "thread-123");

    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body.threadId).toBe("thread-123");
  });

  it("resumeAgentMessageV3 posts threadId + a structured resume, never a message field, and never a capability field", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    await resumeAgentMessageV3("thread-123", {
      type: "ORDER_SELECTED",
      payload: { orderNumber: "U-1002" },
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body).toEqual({
      threadId: "thread-123",
      resume: { type: "ORDER_SELECTED", payload: { orderNumber: "U-1002" } },
    });
    expect(body.message).toBeUndefined();
    expect(body.resume.capability).toBeUndefined();
  });

  it("resumeAgentMessageV3 posts a confirmation resume", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    await resumeAgentMessageV3("thread-123", {
      confirmation: { actionId: "a1", actionType: "SUBMIT_CANCELLATION", accepted: true },
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body).toEqual({
      threadId: "thread-123",
      resume: { confirmation: { actionId: "a1", actionType: "SUBMIT_CANCELLATION", accepted: true } },
    });
  });

  it("throws with response body text when the request fails", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "boom",
    } as Response);

    await expect(sendAgentMessageV3("hi")).rejects.toThrow(/500/);
  });
});
