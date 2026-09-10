import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineReturnReasonPrompt } from "@/components/assistant/inline/InlineReturnReasonPrompt";

describe("InlineReturnReasonPrompt", () => {
  it("shows a loading state when no options are available yet", () => {
    render(
      <InlineReturnReasonPrompt reasonOptions={[]} isAgentLoading={false} onResumeV2={vi.fn()} />
    );

    expect(screen.getByText(/Loading return reasons/)).toBeInTheDocument();
  });

  it("sends a structured REASON_SELECTED resume when an option is clicked", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineReturnReasonPrompt
        reasonOptions={["Wrong size/fit", "Changed my mind"]}
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    fireEvent.click(screen.getByText("Wrong size/fit"));

    expect(onResumeV2).toHaveBeenCalledWith(
      { type: "REASON_SELECTED", capability: "RETURNS", payload: { reason: "Wrong size/fit" } },
      "Wrong size/fit"
    );
  });
});
