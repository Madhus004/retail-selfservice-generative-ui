import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineConfirmationCard } from "@/components/assistant/inline/InlineConfirmationCard";

describe("InlineConfirmationCard", () => {
  it("renders the PENDING preview and calls onResumeV2 with a confirmation payload on Confirm", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineConfirmationCard
        phase="PENDING"
        preview={{
          orderNumber: "U-1001",
          returnedItems: [
            { itemName: "AirKnit Running Shoes", color: "Black / White", size: "9", quantity: 1 },
          ],
          reason: "wrong size",
          refundEstimate: 98,
        }}
        pending={{ actionId: "action-1", actionType: "CREATE_RETURN" }}
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    expect(screen.getByText("Order U-1001")).toBeInTheDocument();
    expect(
      screen.getByText("1 × AirKnit Running Shoes (Black / White, 9)")
    ).toBeInTheDocument();
    expect(screen.getByText("Reason: wrong size")).toBeInTheDocument();
    expect(screen.getByText("Estimated refund: $98.00")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Confirm/i }));

    expect(onResumeV2).toHaveBeenCalledWith(
      { confirmation: { actionId: "action-1", actionType: "CREATE_RETURN", accepted: true } },
      "Confirm"
    );
  });

  it("calls onResumeV2 with accepted: false on Decline", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineConfirmationCard
        phase="PENDING"
        preview={{ orderNumber: "U-1004" }}
        pending={{ actionId: "action-2", actionType: "SUBMIT_CANCELLATION" }}
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Decline/i }));

    expect(onResumeV2).toHaveBeenCalledWith(
      { confirmation: { actionId: "action-2", actionType: "SUBMIT_CANCELLATION", accepted: false } },
      "Decline"
    );
  });

  it("disables both buttons while the agent is loading", () => {
    render(
      <InlineConfirmationCard
        phase="PENDING"
        preview={{ orderNumber: "U-1004" }}
        pending={{ actionId: "action-3", actionType: "SUBMIT_CANCELLATION" }}
        isAgentLoading
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: /Confirm/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Decline/i })).toBeDisabled();
  });

  it("renders a CONFIRMED result without any Confirm/Decline buttons", () => {
    render(
      <InlineConfirmationCard
        phase="CONFIRMED"
        result={{ orderNumber: "U-1002", refundEstimate: 79.22 }}
        isAgentLoading={false}
      />
    );

    expect(screen.getByText("Order U-1002 updated")).toBeInTheDocument();
    expect(screen.getByText("Estimated refund: $79.22")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm/i })).toBeNull();
  });
});
