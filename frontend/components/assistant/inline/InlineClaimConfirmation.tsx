// frontend/components/assistant/inline/InlineClaimConfirmation.tsx
//
// Panel-native replacement for ClaimSubmittedCanvas.

import { CheckCircle2 } from "lucide-react";
import type { ClaimSubmissionResult } from "@/types/order";

export function InlineClaimConfirmation({
  claimResult,
}: {
  claimResult: ClaimSubmissionResult | null;
}) {
  return (
    <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <CheckCircle2 size={14} />
        </div>
        <p className="text-sm font-black tracking-[-0.02em] text-neutral-950">
          Claim submitted
        </p>
      </div>

      <p className="mt-2 text-xs leading-5 text-neutral-600">
        {claimResult?.slaMessage ??
          "Thanks — we submitted your wrong-delivery claim. Our service team will investigate and provide an update within 1–2 days."}
      </p>

      {claimResult?.claimId && (
        <p className="mt-2 text-xs font-bold text-neutral-500">
          Claim ID:{" "}
          <span className="text-neutral-900">{claimResult.claimId}</span>
        </p>
      )}
    </div>
  );
}
