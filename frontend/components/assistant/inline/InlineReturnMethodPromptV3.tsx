// frontend/components/assistant/inline/InlineReturnMethodPromptV3.tsx
//
// V3-only. RETURNS' return-method-selection stage (V3's ReturnMethodPrompt
// a2ui type) — options come from get_return_eligible_items_tool's own
// returnMethods for this order, each button sending a structured
// RETURN_METHOD_SELECTED resume with no "capability" field.
"use client";

import type { StructuredSelectionResumeV3 } from "@/lib/agent-api-v3";

const METHOD_LABELS: Record<string, string> = {
  mail: "Mail it back",
  in_store: "Return in-store",
};

export function InlineReturnMethodPromptV3({
  returnEligibility,
  isAgentLoading,
  onResumeV3,
}: {
  returnEligibility?: { returnMethods?: string[] } | null;
  isAgentLoading: boolean;
  onResumeV3: (resume: StructuredSelectionResumeV3, userFacingLabel: string) => void;
}) {
  const methods = returnEligibility?.returnMethods ?? [];

  if (methods.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        Loading return methods...
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {methods.map((method) => (
        <button
          key={method}
          type="button"
          disabled={isAgentLoading}
          onClick={() =>
            onResumeV3(
              { type: "RETURN_METHOD_SELECTED", payload: { method } },
              METHOD_LABELS[method] ?? method
            )
          }
          className="rounded-full border border-black/10 bg-[#fbfaf7] px-4 py-2 text-xs font-bold text-neutral-700 transition hover:border-black/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {METHOD_LABELS[method] ?? method}
        </button>
      ))}
    </div>
  );
}
