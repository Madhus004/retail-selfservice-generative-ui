import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineDecomposedReturnItem } from "@/components/assistant/inline/InlineDecomposedReturnItem";

describe("InlineDecomposedReturnItem", () => {
  it("shows a loading state when no eligibility data is available yet", () => {
    render(
      <InlineDecomposedReturnItem
        returnEligibility={null}
        isAgentLoading={false}
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByText(/Checking return eligibility/)).toBeInTheDocument();
  });

  it("shows the ineligibility reason when the order can't be returned", () => {
    render(
      <InlineDecomposedReturnItem
        returnEligibility={{
          orderNumber: "U-1003",
          eligible: false,
          reason: "This order hasn't been delivered yet.",
        }}
        isAgentLoading={false}
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByText("This order hasn't been delivered yet.")).toBeInTheDocument();
  });

  it("lists returnable items and the return window when eligible", () => {
    render(
      <InlineDecomposedReturnItem
        returnEligibility={{
          orderNumber: "U-1001",
          eligible: true,
          returnWindowExpiresAt: "2026-06-03",
          items: [
            {
              orderLineId: "OL-1001-1",
              itemName: "AirKnit Running Shoes",
              color: "Black / White",
              size: "9",
              returnableQuantity: 1,
            },
            {
              orderLineId: "OL-1001-2",
              itemName: "Performance Crew Socks",
              color: "Heather Gray",
              size: "M",
              returnableQuantity: 2,
            },
          ],
        }}
        isAgentLoading={false}
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByText("Order U-1001 — select items to return")).toBeInTheDocument();
    expect(screen.getByText("AirKnit Running Shoes")).toBeInTheDocument();
    expect(screen.getByText(/Black \/ White · Size 9 · 1 returnable/)).toBeInTheDocument();
    expect(screen.getByText("Performance Crew Socks")).toBeInTheDocument();
    expect(screen.getByText(/Return window closes 2026-06-03/)).toBeInTheDocument();
  });

  it("submits a structured ITEM_SELECTED resume with the checked items and chosen quantities", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineDecomposedReturnItem
        returnEligibility={{
          orderNumber: "U-1001",
          eligible: true,
          returnWindowExpiresAt: "2026-06-03",
          items: [
            {
              orderLineId: "OL-1001-1",
              itemName: "AirKnit Running Shoes",
              color: "Black / White",
              size: "9",
              returnableQuantity: 1,
            },
            {
              orderLineId: "OL-1001-2",
              itemName: "Performance Crew Socks",
              color: "Heather Gray",
              size: "M",
              returnableQuantity: 2,
            },
          ],
        }}
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    // Continue is disabled until something is checked.
    expect(screen.getByRole("button", { name: /Continue/i })).toBeDisabled();

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));

    expect(onResumeV2).toHaveBeenCalledWith(
      {
        type: "ITEM_SELECTED",
        capability: "RETURNS",
        payload: { selections: [{ orderLineId: "OL-1001-1", quantity: 1 }] },
      },
      "1 item selected"
    );
  });

  it("disables checkboxes and the submit button while the agent is loading", () => {
    render(
      <InlineDecomposedReturnItem
        returnEligibility={{
          orderNumber: "U-1001",
          eligible: true,
          items: [
            {
              orderLineId: "OL-1001-1",
              itemName: "AirKnit Running Shoes",
              color: "Black / White",
              size: "9",
              returnableQuantity: 1,
            },
          ],
        }}
        isAgentLoading
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /Continue/i })).toBeDisabled();
  });
});
