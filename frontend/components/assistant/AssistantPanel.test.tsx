import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AssistantContext } from "@/components/assistant/AssistantProvider";
import { AssistantPanel } from "@/components/assistant/AssistantPanel";

function buildAssistantValue(overrides: Record<string, unknown> = {}) {
  return {
    visibility: "open" as const,
    transcript: [],
    isAgentLoading: false,
    loadingLabel: null,
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
    ...overrides,
  };
}

describe("AssistantPanel close confirmation", () => {
  it("asks for confirmation before closing, and only calls close() once confirmed", () => {
    const close = vi.fn();

    render(
      <AssistantContext.Provider value={buildAssistantValue({ close })}>
        <AssistantPanel />
      </AssistantContext.Provider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Close assistant" }));

    expect(screen.getByText("End this chat?")).toBeInTheDocument();
    expect(close).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "End chat" }));
    expect(close).toHaveBeenCalledOnce();
  });

  it("keeps the conversation visible when the customer cancels the close confirmation", () => {
    const close = vi.fn();

    render(
      <AssistantContext.Provider value={buildAssistantValue({ close })}>
        <AssistantPanel />
      </AssistantContext.Provider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Close assistant" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep chatting" }));

    expect(close).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Ask Uni a question...")).toBeInTheDocument();
  });

  it("dismisses a pending close confirmation when the customer minimizes instead", () => {
    const close = vi.fn();
    const minimize = vi.fn();

    render(
      <AssistantContext.Provider value={buildAssistantValue({ close, minimize })}>
        <AssistantPanel />
      </AssistantContext.Provider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Close assistant" }));
    fireEvent.click(screen.getByRole("button", { name: "Minimize assistant" }));

    expect(minimize).toHaveBeenCalledOnce();
    expect(close).not.toHaveBeenCalled();
  });
});

describe("AssistantPanel agent trace", () => {
  it("is collapsed by default and expands only when toggled", () => {
    render(
      <AssistantContext.Provider
        value={buildAssistantValue({
          agentTrace: [
            {
              id: "t1",
              type: "STATE_DELTA",
              label: "Checking order and customer data",
              status: "complete",
              ts: "2026-01-01T00:00:00.000Z",
            },
          ],
        })}
      >
        <AssistantPanel />
      </AssistantContext.Provider>
    );

    expect(
      screen.queryByText("Checking order and customer data")
    ).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: /show agent trace/i })
    );

    expect(
      screen.getByText("Checking order and customer data")
    ).toBeInTheDocument();
  });
});
