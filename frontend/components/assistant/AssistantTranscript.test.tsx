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
  resumeV2: async () => "",
  resumeV3: async () => "",
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

  it("offers a couple of starter chips in the empty state, not a permanent option menu", () => {
    const whereIsMyOrder = vi.fn();
    const cancelAnOrder = vi.fn();

    render(
      <AssistantContext.Provider
        value={{
          ...baseAssistantValue,
          isAgentLoading: false,
          loadingLabel: null,
          whereIsMyOrder,
          cancelAnOrder,
        }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Where is my order?" }));
    expect(whereIsMyOrder).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Cancel an order" }));
    expect(cancelAnOrder).toHaveBeenCalledOnce();
  });

  it("no longer shows the starter chips once a real conversation has started", () => {
    const turn: TranscriptTurn = {
      role: "assistant",
      id: "1",
      text: "Here's your order.",
      uiMode: "orderStatus",
      a2ui: [{ type: "orderStatus" }],
      canvasData: {},
      ts: new Date().toISOString(),
    };

    render(
      <AssistantContext.Provider
        value={{ ...baseAssistantValue, isAgentLoading: false, loadingLabel: null, transcript: [turn] }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    expect(screen.queryByRole("button", { name: "Where is my order?" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel an order" })).toBeNull();
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

  it("disables a V3 order-selection turn's cards once it's no longer the latest turn", () => {
    // Regression test for a real bug: after the first order card's
    // selection already resolved to a final answer, an OLDER order-list
    // turn's cards stayed fully clickable — selecting one of them sent a
    // resume to a thread with no pending interrupt behind it anymore,
    // which just silently replayed the FIRST order's stale answer instead
    // of doing anything with the newly clicked one.
    const resumeV3 = vi.fn().mockResolvedValue("");

    const order = (orderNumber: string) => ({
      orderNumber,
      status: "Delivered",
      promise: "",
      date: "",
      items: "1 item",
      customerName: "",
      orderPromiseSummary: "",
      promiseStatusLabel: "Met",
      promiseStatusTone: "success" as const,
      customerSummary: "",
      packages: [],
    });

    const staleOrderListTurn: TranscriptTurn = {
      role: "assistant",
      id: "a1",
      text: "I found a few recent orders — which one would you like to check?",
      uiMode: "OrderListPicker",
      a2ui: [{ type: "OrderListPicker" }],
      canvasData: { orders: [order("U-1002"), order("U-1003"), order("U-1004")] },
      engine: "v3",
      ts: "2026-01-01T00:00:00.000Z",
    };
    const latestAnswerTurn: TranscriptTurn = {
      role: "assistant",
      id: "a2",
      text: "Here's the latest status for U-1004.",
      uiMode: "OrderSummaryCard",
      a2ui: [{ type: "OrderSummaryCard" }],
      canvasData: {
        selectedOrder: { ...order("U-1004"), packages: [] },
      },
      engine: "v3",
      ts: "2026-01-01T00:00:01.000Z",
    };

    render(
      <AssistantContext.Provider
        value={{
          ...baseAssistantValue,
          transcript: [staleOrderListTurn, latestAnswerTurn],
          isAgentLoading: false,
          resumeV3,
        }}
      >
        <AssistantTranscript />
      </AssistantContext.Provider>
    );

    const staleCard = screen.getByRole("button", { name: /Order U-1003/ });
    expect(staleCard).toBeDisabled();

    fireEvent.click(staleCard);
    expect(resumeV3).not.toHaveBeenCalled();
  });
});
