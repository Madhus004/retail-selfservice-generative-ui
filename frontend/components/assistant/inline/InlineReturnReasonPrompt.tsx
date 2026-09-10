// frontend/components/assistant/inline/InlineReturnReasonPrompt.tsx
//
// V2-only. RETURNS' reason-selection stage (2026-08 structured-interaction
// fix) — a fixed, backend-declared set of options (never hardcoded twice),
// each button sending a structured REASON_SELECTED resume.
"use client";

import type { StructuredSelectionResume } from "@/lib/agent-api-v2";

export function InlineReturnReasonPrompt({
  reasonOptions,
  isAgentLoading,
  onResumeV2,
}: {
  reasonOptions: string[];
  isAgentLoading: boolean;
  onResumeV2: (resume: StructuredSelectionResume, userFacingLabel: string) => void;
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
          onClick={() =>
            onResumeV2(
              { type: "REASON_SELECTED", capability: "RETURNS", payload: { reason } },
              reason
            )
          }
          className="rounded-full border border-black/10 bg-[#fbfaf7] px-4 py-2 text-xs font-bold text-neutral-700 transition hover:border-black/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {reason}
        </button>
      ))}
    </div>
  );
}
