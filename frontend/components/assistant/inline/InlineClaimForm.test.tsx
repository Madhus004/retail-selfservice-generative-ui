import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineClaimForm } from "@/components/assistant/inline/InlineClaimForm";
import type { OrderScenario } from "@/types/order";

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

describe("InlineClaimForm", () => {
  it("submits with the order number, package number, and entered details", () => {
    const onSubmitClaim = vi.fn();

    render(<InlineClaimForm order={order} onSubmitClaim={onSubmitClaim} />);

    fireEvent.click(screen.getByRole("button", { name: /submit claim/i }));

    expect(onSubmitClaim).toHaveBeenCalledWith(
      expect.objectContaining({
        orderNumber: "U-1002",
        packageNumber: 1,
        preferredContactMethod: "email",
      })
    );
  });

  it("disables submit when the issue description is cleared", () => {
    const onSubmitClaim = vi.fn();

    render(<InlineClaimForm order={order} onSubmitClaim={onSubmitClaim} />);

    fireEvent.change(screen.getByLabelText(/what happened/i), {
      target: { value: "   " },
    });

    expect(screen.getByRole("button", { name: /submit claim/i })).toBeDisabled();
  });

  it("disables submit when there is no order", () => {
    render(<InlineClaimForm order={null} onSubmitClaim={() => {}} />);

    expect(screen.getByRole("button", { name: /submit claim/i })).toBeDisabled();
  });
});
