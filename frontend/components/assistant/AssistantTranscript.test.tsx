import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AssistantContext } from "@/components/assistant/AssistantProvider";
import { AssistantTranscript } from "@/components/assistant/AssistantTranscript";
import type { TranscriptTurn } from "@/lib/assistant-reducer";

const baseAssistantValue = {
  visibility: "open" as const,
  transcript: [],
  isAgentLoading: true,
  loadingLabel: "Checking your recent orders...",
  loadingOrderNumber: null,
  agentTrace: [],
  setPageContext: () => {},
  open: () => {},
  minimize: () => {},
  close: () => {},
  whereIsMyOrder: () => {},
  cancelAnOrder: () => {},
  selectOrder: () => {},
  reportWrongDelivery: () => {},
  submitWrongDeliveryClaim: () => {},
  submitOrderCancellation: () => {},
  backToOrders: () => {},
  backToDashboard: () => {},
  sendFreeText: async () => "",
};

describe("AssistantTranscript", () => {
  it("renders exactly one loading indicator while the agent is working", () => {
    render(
      <AssistantContext.Provider value={baseAssistantValue}>
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    expect(
      screen.getAllByText("Checking your recent orders...")
    ).toHaveLength(1);
  });

  it("shows the welcome prompt instead of a loading indicator when idle with no history", () => {
    render(
      <AssistantContext.Provider
        value={{ ...baseAssistantValue, isAgentLoading: false, loadingLabel: null }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    expect(screen.queryByText("Checking your recent orders...")).toBeNull();
    expect(
      screen.getByText(/Hi! I.m Uni, your AI self-service associate\./)
    ).toBeInTheDocument();
  });

  it("scrolls to the start of a newly appended assistant turn, not the bottom", () => {
    const scrollIntoViewSpy = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});

    const userTurn: TranscriptTurn = {
      role: "user",
      id: "u1",
      text: "Where is my order?",
      ts: "2026-01-01T00:00:00.000Z",
    };
    const assistantTurn: TranscriptTurn = {
      role: "assistant",
      id: "a1",
      text: "Here are your recent orders.",
      uiMode: "orderSelection",
      a2ui: [{ type: "orderSelection" }],
      canvasData: { orders: [] },
      ts: "2026-01-01T00:00:01.000Z",
    };

    const { rerender } = render(
      <AssistantContext.Provider
        value={{ ...baseAssistantValue, transcript: [userTurn], isAgentLoading: true }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    scrollIntoViewSpy.mockClear();

    rerender(
      <AssistantContext.Provider
        value={{
          ...baseAssistantValue,
          transcript: [userTurn, assistantTurn],
          isAgentLoading: false,
        }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    expect(scrollIntoViewSpy).toHaveBeenCalledWith(
      expect.objectContaining({ block: "start" })
    );

    scrollIntoViewSpy.mockRestore();
  });

  it("scrolls to the bottom sentinel when a new user turn starts a request", () => {
    const scrollIntoViewSpy = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});

    const { rerender } = render(
      <AssistantContext.Provider
        value={{ ...baseAssistantValue, transcript: [], isAgentLoading: false }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    scrollIntoViewSpy.mockClear();

    const userTurn: TranscriptTurn = {
      role: "user",
      id: "u1",
      text: "Where is my order?",
      ts: "2026-01-01T00:00:00.000Z",
    };

    rerender(
      <AssistantContext.Provider
        value={{ ...baseAssistantValue, transcript: [userTurn], isAgentLoading: true }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    expect(scrollIntoViewSpy).toHaveBeenCalledWith(
      expect.objectContaining({ block: "end" })
    );

    scrollIntoViewSpy.mockRestore();
  });

  it("renders suggestedReplies as generic chips for the latest turn and sends the label on click", () => {
    const sendFreeText = vi.fn().mockResolvedValue("");

    const assistantTurn: TranscriptTurn = {
      role: "assistant",
      id: "a1",
      text: "I found your recent Unicorn orders.",
      uiMode: "orderSelection",
      a2ui: [{ type: "orderSelection" }],
      canvasData: { orders: [] },
      suggestedReplies: ["My order isn't listed"],
      ts: "2026-01-01T00:00:00.000Z",
    };

    render(
      <AssistantContext.Provider
        value={{
          ...baseAssistantValue,
          transcript: [assistantTurn],
          isAgentLoading: false,
          sendFreeText,
        }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    const chip = screen.getByRole("button", { name: "My order isn't listed" });
    fireEvent.click(chip);

    expect(sendFreeText).toHaveBeenCalledWith("My order isn't listed");
  });

  it("does not render suggestedReplies chips while a new request is loading", () => {
    const assistantTurn: TranscriptTurn = {
      role: "assistant",
      id: "a1",
      text: "I found your recent Unicorn orders.",
      uiMode: "orderSelection",
      a2ui: [{ type: "orderSelection" }],
      canvasData: { orders: [] },
      suggestedReplies: ["My order isn't listed"],
      ts: "2026-01-01T00:00:00.000Z",
    };

    render(
      <AssistantContext.Provider
        value={{
          ...baseAssistantValue,
          transcript: [assistantTurn],
          isAgentLoading: true,
        }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    expect(
      screen.queryByRole("button", { name: "My order isn't listed" })
    ).toBeNull();
  });
});
