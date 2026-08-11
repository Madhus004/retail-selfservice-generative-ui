import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineCancellationBuilder } from "@/components/assistant/inline/InlineCancellationBuilder";
import type { CancellationEligibleOrder } from "@/types/cancellation";

const twoOrders: CancellationEligibleOrder[] = [
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
  {
    orderNumber: "U-1005",
    orderDate: "2026-05-10",
    orderStatus: "Processing",
    currency: "USD",
    items: [
      {
        orderLineId: "OL-1005-1",
        itemName: "Everyday Denim",
        color: "Indigo",
        size: "32",
        price: 78,
        quantity: 1,
        cancellableQuantity: 1,
      },
    ],
  },
];

describe("InlineCancellationBuilder", () => {
  it("shows no eligible orders message when the list is empty", () => {
    render(<InlineCancellationBuilder eligibleOrders={[]} onSubmit={() => {}} />);

    expect(
      screen.getByText(/No orders are currently eligible for cancellation/)
    ).toBeInTheDocument();
  });

  it("starts at order selection when multiple orders are eligible, and advances on selection", () => {
    render(
      <InlineCancellationBuilder eligibleOrders={twoOrders} onSubmit={() => {}} />
    );

    expect(screen.getByText("Order U-1004")).toBeInTheDocument();
    expect(screen.getByText("Order U-1005")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Order U-1004"));

    expect(screen.getByText("Lightweight Hoodie")).toBeInTheDocument();
  });

  it("always shows order selection first, even when only one order is eligible", () => {
    render(
      <InlineCancellationBuilder
        eligibleOrders={[twoOrders[0]]}
        onSubmit={() => {}}
      />
    );

    expect(screen.getByText("Order U-1004")).toBeInTheDocument();
    expect(screen.queryByText("Lightweight Hoodie")).toBeNull();

    fireEvent.click(screen.getByText("Order U-1004"));
    expect(screen.getByText("Lightweight Hoodie")).toBeInTheDocument();
  });

  it("disables Continue until at least one item is checked", () => {
    render(
      <InlineCancellationBuilder
        eligibleOrders={[twoOrders[0]]}
        onSubmit={() => {}}
      />
    );

    fireEvent.click(screen.getByText("Order U-1004"));

    const continueButton = screen.getByRole("button", { name: "Continue" });
    expect(continueButton).toBeDisabled();

    fireEvent.click(screen.getByText("Lightweight Hoodie"));
    expect(continueButton).not.toBeDisabled();
  });

  it("respects the cancellable quantity bounds when stepping quantity", () => {
    render(
      <InlineCancellationBuilder
        eligibleOrders={[twoOrders[0]]}
        onSubmit={() => {}}
      />
    );

    fireEvent.click(screen.getByText("Order U-1004"));
    fireEvent.click(screen.getByText("Everyday Crew Tee"));

    const increment = screen.getAllByRole("button").find((button) =>
      button.querySelector("svg.lucide-plus")
    )!;
    const decrement = screen.getAllByRole("button").find((button) =>
      button.querySelector("svg.lucide-minus")
    )!;

    expect(screen.getByText("1")).toBeInTheDocument();

    fireEvent.click(increment);
    expect(screen.getByText("2")).toBeInTheDocument();

    // Cancellable quantity is 2 — a further increment should not exceed it.
    fireEvent.click(increment);
    expect(screen.getByText("2")).toBeInTheDocument();

    fireEvent.click(decrement);
    fireEvent.click(decrement);
    // Quantity floors at 1, not 0.
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("calls onSubmit exactly once with the right arguments and disables the button afterward", () => {
    const onSubmit = vi.fn();

    render(
      <InlineCancellationBuilder
        eligibleOrders={[twoOrders[0]]}
        onSubmit={onSubmit}
      />
    );

    fireEvent.click(screen.getByText("Order U-1004"));
    fireEvent.click(screen.getByText("Lightweight Hoodie"));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Review cancellation" })
    );
    const confirmButton = screen.getByRole("button", {
      name: /confirm cancellation/i,
    });
    fireEvent.click(confirmButton);

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith(
      "U-1004",
      [{ orderLineId: "OL-1004-1", quantity: 1 }],
      "Found a better price"
    );

    fireEvent.click(confirmButton);
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("supports navigating back through steps", () => {
    render(
      <InlineCancellationBuilder eligibleOrders={twoOrders} onSubmit={() => {}} />
    );

    fireEvent.click(screen.getByText("Order U-1004"));
    expect(screen.getByText("Lightweight Hoodie")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByText("Order U-1004")).toBeInTheDocument();
    expect(screen.getByText("Order U-1005")).toBeInTheDocument();
  });
});
