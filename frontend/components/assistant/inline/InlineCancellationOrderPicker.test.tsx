import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineCancellationOrderPicker } from "@/components/assistant/inline/InlineCancellationOrderPicker";
import type { CancellationEligibleOrder } from "@/types/cancellation";

const ORDERS: CancellationEligibleOrder[] = [
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
];

describe("InlineCancellationOrderPicker", () => {
  it("shows an empty state when there are no eligible orders", () => {
    render(
      <InlineCancellationOrderPicker eligibleOrders={[]} isAgentLoading={false} onResumeV2={vi.fn()} />
    );

    expect(screen.getByText(/No orders are currently eligible/)).toBeInTheDocument();
  });

  it("sends a structured ORDER_SELECTED resume when an order is clicked", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineCancellationOrderPicker
        eligibleOrders={ORDERS}
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    fireEvent.click(screen.getByText("Order U-1004"));

    expect(onResumeV2).toHaveBeenCalledWith(
      { type: "ORDER_SELECTED", capability: "CANCELLATION", payload: { orderNumber: "U-1004" } },
      "Order U-1004"
    );
  });

  it("disables order buttons while the agent is loading", () => {
    render(
      <InlineCancellationOrderPicker eligibleOrders={ORDERS} isAgentLoading onResumeV2={vi.fn()} />
    );

    expect(screen.getByText("Order U-1004").closest("button")).toBeDisabled();
  });
});
