import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineCancellationItemPicker } from "@/components/assistant/inline/InlineCancellationItemPicker";
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
      {
        orderLineId: "OL-1004-2",
        itemName: "Everyday Crew Tee",
        color: "Heather Grey",
        size: "M",
        price: 19.25,
        quantity: 2,
        cancellableQuantity: 2,
      },
    ],
  },
];

describe("InlineCancellationItemPicker", () => {
  it("shows a loading state when the order hasn't been found yet", () => {
    render(
      <InlineCancellationItemPicker
        eligibleOrders={[]}
        orderNumber="U-1004"
        isAgentLoading={false}
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByText(/Loading order details/)).toBeInTheDocument();
  });

  it("submits a structured ITEM_SELECTED resume for the checked item", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineCancellationItemPicker
        eligibleOrders={ORDERS}
        orderNumber="U-1004"
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    expect(screen.getByRole("button", { name: /Continue/i })).toBeDisabled();

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));

    expect(onResumeV2).toHaveBeenCalledWith(
      {
        type: "ITEM_SELECTED",
        capability: "CANCELLATION",
        payload: { selections: [{ orderLineId: "OL-1004-1", quantity: 1 }] },
      },
      "1 item selected"
    );
  });

  it("lets the quantity be adjusted up to the cancellable maximum", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineCancellationItemPicker
        eligibleOrders={ORDERS}
        orderNumber="U-1004"
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]); // Everyday Crew Tee, cancellableQuantity 2

    fireEvent.click(screen.getByRole("button", { name: "Increase quantity for Everyday Crew Tee" }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));

    expect(onResumeV2).toHaveBeenCalledWith(
      {
        type: "ITEM_SELECTED",
        capability: "CANCELLATION",
        payload: { selections: [{ orderLineId: "OL-1004-2", quantity: 2 }] },
      },
      "1 item selected"
    );
  });
});
