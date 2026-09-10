// frontend/components/assistant/inline/InlineReturnReasonPromptV3.tsx
//
// V3-only. RETURNS' reason-selection stage (V3's ReturnReasonPrompt a2ui
// type) — a fixed, backend-declared set of options, each button sending a
// structured REASON_SELECTED resume with no "capability" field.
"use client";

import type { StructuredSelectionResumeV3 } from "@/lib/agent-api-v3";

export function InlineReturnReasonPromptV3({
  reasonOptions,
  isAgentLoading,
  onResumeV3,
}: {
  reasonOptions: string[];
  isAgentLoading: boolean;
  onResumeV3: (resume: StructuredSelectionResumeV3, userFacingLabel: string) => void;
}) {
  if (reasonOptions.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        Loading return reasons...
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {reasonOptions.map((reason) => (
        <button
          key={reason}
          type="button"
          disabled={isAgentLoading}
          onClick={() => onResumeV3({ type: "REASON_SELECTED", payload: { reason } }, reason)}
          className="rounded-full border border-black/10 bg-[#fbfaf7] px-4 py-2 text-xs font-bold text-neutral-700 transition hover:border-black/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {reason}
        </button>
      ))}
    </div>
  );
}
