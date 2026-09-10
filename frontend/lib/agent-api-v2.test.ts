import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  resumeAgentMessageV2,
  sendAgentMessageV2,
  type AgentChatResponseV2,
} from "@/lib/agent-api-v2";

function mockResponse(body: AgentChatResponseV2) {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

const SAMPLE_RESPONSE: AgentChatResponseV2 = {
  message: "Here's your order.",
  capability: "ORDER_STATUS",
  orderNumber: "U-1002",
  uiState: {
    uiMode: "orderStatus",
    assistantMessage: "Here's your order.",
    canvasData: {},
    a2ui: [{ type: "orderStatus" }],
  },
  status: "FINAL",
  threadId: "thread-123",
  runId: "run-456",
};

describe("agent-api-v2", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sendAgentMessageV2 posts to /v2/agent/chat with the message and omits threadId on the first turn", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    const result = await sendAgentMessageV2("Where is my order?");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/v2/agent/chat");
    expect(init?.method).toBe("POST");

    const body = JSON.parse(init?.body as string);
    expect(body).toEqual({ message: "Where is my order?", threadId: undefined, pageContext: undefined });
    expect(result).toEqual(SAMPLE_RESPONSE);
  });

  it("sendAgentMessageV2 threads a continuing threadId through", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    await sendAgentMessageV2("Why is it late?", "thread-123");

    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body.threadId).toBe("thread-123");
  });

  it("resumeAgentMessageV2 posts threadId + a structured resume, never a message field", async () => {
    const fetchMock = vi.mocked(fetch).mockResolvedValue(mockResponse(SAMPLE_RESPONSE));

    await resumeAgentMessageV2("thread-123", {
      confirmation: { actionId: "a1", actionType: "CREATE_RETURN", accepted: true },
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(body).toEqual({
      threadId: "thread-123",
      resume: { confirmation: { actionId: "a1", actionType: "CREATE_RETURN", accepted: true } },
    });
    expect(body.message).toBeUndefined();
  });

  it("throws with response body text when the request fails", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "boom",
    } as Response);

    await expect(sendAgentMessageV2("hi")).rejects.toThrow(/500/);
  });
});
