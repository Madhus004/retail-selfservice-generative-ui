// frontend/components/ClaimSubmittedCanvas.tsx

import { CheckCircle2 } from "lucide-react";
import type { ClaimSubmissionResult } from "@/types/order";

export function ClaimSubmittedCanvas({
  claimResult,
  onBackToOrders,
}: {
  claimResult: ClaimSubmissionResult | null;
  onBackToOrders: () => void;
}) {
  return (
    <div className="flex min-h-full items-center justify-center rounded-[1.5rem] bg-white p-8">
      <div className="max-w-2xl rounded-[2rem] border border-black/10 bg-[#fbfaf7] p-8 text-center shadow-sm">
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <CheckCircle2 size={30} />
        </div>

        <p className="mb-3 text-xs font-black uppercase tracking-[0.28em] text-neutral-400">
          Claim submitted
        </p>

        <h2 className="text-4xl font-black tracking-[-0.055em] text-neutral-950">
          We’re looking into it.
        </h2>

        <p className="mt-4 text-sm leading-6 text-neutral-600">
          {claimResult?.slaMessage ??
            "Thanks — we submitted your wrong-delivery claim. Our service team will investigate and provide an update within 1–2 days."}
        </p>

        {claimResult?.claimId && (
          <div className="mt-6 rounded-3xl border border-black/10 bg-white p-5">
            <p className="text-xs font-black uppercase tracking-[0.24em] text-neutral-400">
              Claim ID
            </p>
            <p className="mt-2 text-xl font-black">{claimResult.claimId}</p>
          </div>
        )}

        <button
          onClick={onBackToOrders}
          className="mt-8 rounded-full bg-black px-6 py-4 text-sm font-black text-white transition hover:bg-neutral-800"
        >
          Back to orders
        </button>
      </div>
    </div>
  );
}