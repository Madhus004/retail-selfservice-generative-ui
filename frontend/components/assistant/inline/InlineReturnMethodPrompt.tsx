// frontend/components/assistant/inline/InlineReturnMethodPrompt.tsx
//
// V2-only. RETURNS' return-method-selection stage (2026-08 structured-
// interaction fix) — options come from get_return_eligible_items_tool's
// own returnMethods for this order (the only source of truth), each
// button sending a structured RETURN_METHOD_SELECTED resume.
"use client";

import type { StructuredSelectionResume } from "@/lib/agent-api-v2";

const METHOD_LABELS: Record<string, string> = {
  mail: "Mail it back",
  in_store: "Return in-store",
};

export function InlineReturnMethodPrompt({
  returnEligibility,
  isAgentLoading,
  onResumeV2,
}: {
  returnEligibility?: { returnMethods?: string[] } | null;
  isAgentLoading: boolean;
  onResumeV2: (resume: StructuredSelectionResume, userFacingLabel: string) => void;
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
            onResumeV2(
              { type: "RETURN_METHOD_SELECTED", capability: "RETURNS", payload: { method } },
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
