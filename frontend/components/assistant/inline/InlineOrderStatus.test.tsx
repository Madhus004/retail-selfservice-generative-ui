import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineOrderStatus } from "@/components/assistant/inline/InlineOrderStatus";
import type { OrderScenario } from "@/types/order";

function buildOrder(overrides: Partial<OrderScenario> = {}): OrderScenario {
  return {
    orderNumber: "U-1002",
    status: "Delivered",
    promise: "Promised delivery: Missed",
    date: "May 2, 2026",
    items: "1 item · 1 package",
    customerName: "Demo Customer",
    orderPromiseSummary: "Original promise: May 6, 2026",
    promiseStatusLabel: "Missed",
    promiseStatusTone: "danger",
    customerSummary: "Your order arrived later than promised.",
    packages: [
      {
        packageNumber: 1,
        trackingNumber: "1Z999AA10123456784",
        carrier: "UPS",
        status: "Delivered late",
        promisedDeliveryResult: "Missed",
        promisedDelivery: "May 6, 2026",
        actualOrEstimatedDelivery: "May 8, 2026",
        fullTrackingUrl: "https://example.com/track/1Z999AA10123456784",
        items: [],
        milestones: [
          { label: "Shipped", date: "May 3, 2026", position: 20, tone: "success" },
          { label: "Delivered", date: "May 8, 2026", position: 90, tone: "danger" },
          { label: "Original promise", date: "May 6, 2026", position: 80, tone: "promise" },
        ],
      },
    ],
    ...overrides,
  };
}

describe("InlineOrderStatus", () => {
  it("does not render a service-recovery card when order.serviceRecovery is absent", () => {
    render(
      <InlineOrderStatus order={buildOrder()} onReportWrongDelivery={() => {}} />
    );

    expect(screen.queryByText(/We.ve made this right|A little something/)).toBeNull();
  });

  it("renders the compact service-recovery card when order.serviceRecovery is present", () => {
    const order = buildOrder({
      serviceRecovery: {
        title: "We’ve made this right",
        description: "We refunded your shipping fee.",
        badge: "Shipping refunded",
        tone: "refund",
      },
    });

    render(<InlineOrderStatus order={order} onReportWrongDelivery={() => {}} />);

    expect(screen.getByText("We’ve made this right")).toBeInTheDocument();
    expect(screen.getByText("Shipping refunded")).toBeInTheDocument();
  });

  it("only shows Report delivery issue when the package has delivery proof", () => {
    const onReportWrongDelivery = vi.fn();

    const { rerender } = render(
      <InlineOrderStatus
        order={buildOrder()}
        onReportWrongDelivery={onReportWrongDelivery}
      />
    );

    expect(screen.queryByText("Report delivery issue")).toBeNull();

    const orderWithProof = buildOrder();
    orderWithProof.packages[0].deliveryProof = {
      deliveredAt: "May 8, 2026",
      locationNote: "Front porch",
      imageDescription: "Delivery proof photo",
    };

    rerender(
      <InlineOrderStatus
        order={orderWithProof}
        onReportWrongDelivery={onReportWrongDelivery}
      />
    );

    expect(screen.getByText("Report delivery issue")).toBeInTheDocument();
  });
});
