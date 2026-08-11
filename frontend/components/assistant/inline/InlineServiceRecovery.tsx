// frontend/components/assistant/inline/InlineServiceRecovery.tsx
//
// Compact coupon/refund card. Rendered by InlineOrderStatus when
// order.serviceRecovery is present — same derivation pattern as the old
// PromiseDashboardCanvas's ServiceRecoveryStrip, just compact.

import { Gift } from "lucide-react";
import type { ServiceRecovery } from "@/types/order";

export function InlineServiceRecovery({
  recovery,
}: {
  recovery: ServiceRecovery;
}) {
  const isRefund = recovery.tone === "refund";

  return (
    <div
      className={`rounded-2xl border p-3 ${
        isRefund ? "border-rose-200 bg-rose-50" : "border-amber-200 bg-amber-50"
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            isRefund ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"
          }`}
        >
          <Gift size={14} />
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-black tracking-[-0.02em] text-neutral-950">
            {recovery.title}
          </p>
          <p className="mt-0.5 text-xs leading-4 text-neutral-700">
            {recovery.description}
          </p>

          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-black text-neutral-900 ring-1 ring-black/10">
              {recovery.badge}
            </span>
            {recovery.secondaryBadge && (
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-black text-neutral-900 ring-1 ring-black/10">
                {recovery.secondaryBadge}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
