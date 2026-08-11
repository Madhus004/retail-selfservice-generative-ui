import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { A2UIRenderer } from "@/components/A2UIRenderer";
import type { OrderScenario } from "@/types/order";

const noop = () => {};

const order: OrderScenario = {
  orderNumber: "U-1002",
  status: "Delivered",
  promise: "Promised delivery: Missed",
  date: "May 2, 2026",
  items: "1 item",
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
      fullTrackingUrl: "https://example.com/track",
      items: [],
      milestones: [],
    },
  ],
};

const baseProps = {
  isAgentLoading: false,
  loadingOrderNumber: null,
  claimResult: null,
  eligibleOrders: [],
  cancellationResult: null,
  onSelectOrder: noop,
  onReportWrongDelivery: noop,
  onSubmitWrongDeliveryClaim: noop,
  onSubmitOrderCancellation: noop,
};

describe("A2UIRenderer (renders the compact inline catalog, not the old canvas components)", () => {
  it("renders InlineOrderList for orderSelection, not the old OrderSelectionCanvas dashboard heading", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="orderSelection"
        components={[{ type: "orderSelection" }]}
        selectedOrder={null}
        orders={[order]}
      />
    );

    expect(screen.getByText("Order U-1002")).toBeInTheDocument();
    expect(screen.queryByText("Select an order to track.")).toBeNull();
  });

  it("renders InlineOrderStatus for promiseDashboard, not the old PromiseDashboardCanvas dashboard heading", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="promiseDashboard"
        components={[{ type: "promiseDashboard" }]}
        selectedOrder={order}
        orders={[]}
      />
    );

    expect(screen.getByText("Track package")).toBeInTheDocument();
    expect(screen.queryByText("Promise Sense Dashboard")).toBeNull();
  });

  it("renders InlineClaimForm for wrongDeliveryClaim", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="wrongDeliveryClaim"
        components={[{ type: "wrongDeliveryClaim" }]}
        selectedOrder={order}
        orders={[]}
      />
    );

    expect(
      screen.getByRole("button", { name: /submit claim/i })
    ).toBeInTheDocument();
    expect(screen.queryByText("Let's investigate this delivery.")).toBeNull();
  });

  it("renders InlineClaimConfirmation for claimSubmitted", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="claimSubmitted"
        components={[{ type: "claimSubmitted" }]}
        selectedOrder={null}
        orders={[]}
        claimResult={{
          claimId: "CLAIM-10021234",
          orderNumber: "U-1002",
          status: "submitted",
          submittedAt: "2026-05-02T00:00:00.000Z",
          slaMessage: "We are on it.",
        }}
      />
    );

    expect(screen.getByText("Claim submitted")).toBeInTheDocument();
    expect(screen.getByText(/CLAIM-10021234/)).toBeInTheDocument();
  });

  it("renders InlineWelcome by default", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="welcome"
        components={[{ type: "welcome" }]}
        selectedOrder={null}
        orders={[]}
      />
    );

    expect(
      screen.getByText(/I can help with order tracking/)
    ).toBeInTheDocument();
  });

  it("renders InlineCancellationBuilder for cancellationBuilder", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="cancellationBuilder"
        components={[{ type: "cancellationBuilder" }]}
        selectedOrder={null}
        orders={[]}
        eligibleOrders={[
          {
            orderNumber: "U-1004",
            orderDate: "2026-05-09",
            orderStatus: "Processing",
            currency: "USD",
            items: [
              {
                orderLineId: "OL-1004-1",
                itemName: "Lightweight Hoodie",
                color: "Charcoal",
                size: "L",
                price: 58,
                quantity: 1,
                cancellableQuantity: 1,
              },
            ],
          },
        ]}
      />
    );

    expect(screen.getByText("Order U-1004")).toBeInTheDocument();
  });

  it("renders InlineCancellationConfirmation for cancellationConfirmed", () => {
    render(
      <A2UIRenderer
        {...baseProps}
        uiMode="cancellationConfirmed"
        components={[{ type: "cancellationConfirmed" }]}
        selectedOrder={null}
        orders={[]}
        cancellationResult={{
          cancellationId: "CANC-U1004-ABC123",
          orderNumber: "U-1004",
          status: "submitted",
          cancelledItems: [
            {
              itemName: "Lightweight Hoodie",
              color: "Charcoal",
              size: "L",
              quantity: 1,
            },
          ],
          reason: "No longer needed",
          resultingOrderStatus: "Cancelled",
        }}
      />
    );

    expect(screen.getByText("Cancellation submitted")).toBeInTheDocument();
    expect(screen.getByText(/CANC-U1004-ABC123/)).toBeInTheDocument();
  });
});
