import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineReturnMethodPrompt } from "@/components/assistant/inline/InlineReturnMethodPrompt";

describe("InlineReturnMethodPrompt", () => {
  it("shows a loading state when no methods are available yet", () => {
    render(
      <InlineReturnMethodPrompt
        returnEligibility={null}
        isAgentLoading={false}
        onResumeV2={vi.fn()}
      />
    );

    expect(screen.getByText(/Loading return methods/)).toBeInTheDocument();
  });

  it("sends a structured RETURN_METHOD_SELECTED resume when a method is clicked", () => {
    const onResumeV2 = vi.fn();

    render(
      <InlineReturnMethodPrompt
        returnEligibility={{ returnMethods: ["mail", "in_store"] }}
        isAgentLoading={false}
        onResumeV2={onResumeV2}
      />
    );

    fireEvent.click(screen.getByText("Return in-store"));

    expect(onResumeV2).toHaveBeenCalledWith(
      { type: "RETURN_METHOD_SELECTED", capability: "RETURNS", payload: { method: "in_store" } },
      "Return in-store"
    );
  });
});
