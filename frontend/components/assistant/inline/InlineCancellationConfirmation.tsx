// frontend/components/assistant/inline/InlineCancellationConfirmation.tsx

import { CheckCircle2 } from "lucide-react";
import type { CancellationResult } from "@/types/cancellation";

export function InlineCancellationConfirmation({
  cancellationResult,
}: {
  cancellationResult: CancellationResult | null;
}) {
  return (
    <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <CheckCircle2 size={14} />
        </div>
        <p className="text-sm font-black tracking-[-0.02em] text-neutral-950">
          Cancellation submitted
        </p>
      </div>

      {cancellationResult && (
        <>
          <div className="mt-2 space-y-1">
            {cancellationResult.cancelledItems.map((item, index) => (
              <p key={index} className="text-xs text-neutral-700">
                {item.quantity} × {item.itemName} ({item.color}, {item.size})
              </p>
            ))}
          </div>

          <p className="mt-2 text-xs font-bold text-neutral-500">
            Order status:{" "}
            <span className="text-neutral-900">
              {cancellationResult.resultingOrderStatus}
            </span>
          </p>
          <p className="mt-1 text-xs font-bold text-neutral-500">
            Confirmation ID:{" "}
            <span className="text-neutral-900">
              {cancellationResult.cancellationId}
            </span>
          </p>
        </>
      )}
    </div>
  );
}
