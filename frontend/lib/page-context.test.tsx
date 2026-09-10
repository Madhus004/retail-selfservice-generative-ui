import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AssistantContext } from "@/components/assistant/AssistantProvider";
import { usePageContext, type PageContext } from "@/lib/page-context";

function TestHarness({ context }: { context: PageContext }) {
  usePageContext(context);
  return null;
}

function buildAssistantValue(setPageContext: (context: PageContext | null) => void) {
  return {
    visibility: "open" as const,
    transcript: [],
    isAgentLoading: false,
    loadingLabel: null,
    loadingOrderNumber: null,
    agentTrace: [],
    setPageContext,
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
}

describe("usePageContext", () => {
  it("registers the page context on mount and clears it on unmount", () => {
    const setPageContext = vi.fn();

    const { unmount } = render(
      <AssistantContext.Provider value={buildAssistantValue(setPageContext)}>
        <TestHarness context={{ page: "ORDER_DETAILS", orderNumber: "U-1002" }} />
      </AssistantContext.Provider>
    );

    expect(setPageContext).toHaveBeenCalledWith({
      page: "ORDER_DETAILS",
      orderNumber: "U-1002",
    });

    unmount();

    expect(setPageContext).toHaveBeenLastCalledWith(null);
  });

  it("re-registers when the underlying context value changes", () => {
    const setPageContext = vi.fn();

    const { rerender } = render(
      <AssistantContext.Provider value={buildAssistantValue(setPageContext)}>
        <TestHarness context={{ page: "ORDER_DETAILS", orderNumber: "U-1001" }} />
      </AssistantContext.Provider>
    );

    setPageContext.mockClear();

    rerender(
      <AssistantContext.Provider value={buildAssistantValue(setPageContext)}>
        <TestHarness context={{ page: "ORDER_DETAILS", orderNumber: "U-1002" }} />
      </AssistantContext.Provider>
    );

    expect(setPageContext).toHaveBeenCalledWith({
      page: "ORDER_DETAILS",
      orderNumber: "U-1002",
    });
  });
});
