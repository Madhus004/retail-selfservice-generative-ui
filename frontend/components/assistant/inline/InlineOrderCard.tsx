// frontend/components/assistant/inline/InlineOrderCard.tsx
//
// A single compact order row used inside InlineOrderList. No fixed-size icon
// box and `truncate` on every text node — the old OrderSelectionCanvas's
// 56px icon + unbounded text caused overflow at panel width.

import { ArrowRight, Loader2 } from "lucide-react";
import type { OrderScenario, PromiseTone } from "@/types/order";

const toneClass: Record<PromiseTone, string> = {
  success: "bg-emerald-50 text-emerald-700",
  warning: "bg-amber-50 text-amber-700",
  danger: "bg-rose-50 text-rose-700",
  neutral: "bg-neutral-100 text-neutral-600",
};

export function InlineOrderCard({
  order,
  isLoading,
  disabled,
  onSelect,
}: {
  order: OrderScenario;
  isLoading: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      disabled={disabled}
      className="flex w-full items-center justify-between gap-3 rounded-2xl border border-black/10 bg-white px-3 py-2.5 text-left transition hover:border-black/30 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-black tracking-[-0.02em] text-neutral-950">
            Order {order.orderNumber}
          </p>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-black ${toneClass[order.promiseStatusTone]}`}
          >
            {order.promiseStatusLabel}
          </span>
        </div>
        <p className="mt-0.5 truncate text-xs text-neutral-500">
          {order.status} · {order.items}
        </p>
      </div>

      {isLoading ? (
        <Loader2 size={14} className="shrink-0 animate-spin text-neutral-500" />
      ) : (
        <ArrowRight size={14} className="shrink-0 text-neutral-400" />
      )}
    </button>
  );
}
