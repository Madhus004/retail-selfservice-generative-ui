// frontend/components/assistant/inline/InlineCancellationOrderPicker.tsx
//
// V2-only. CANCELLATION's order-selection stage — genuinely interactive
// (2026-08 structured-interaction fix; previously this screen fell back to
// plain prose since no component existed for cancellationOrderSelection).
// A click sends a structured ORDER_SELECTED resume, never free text.
"use client";

import type { StructuredSelectionResume } from "@/lib/agent-api-v2";
import type { CancellationEligibleOrder } from "@/types/cancellation";

export function InlineCancellationOrderPicker({
  eligibleOrders,
  isAgentLoading,
  onResumeV2,
}: {
  eligibleOrders: CancellationEligibleOrder[];
  isAgentLoading: boolean;
  onResumeV2: (resume: StructuredSelectionResume, userFacingLabel: string) => void;
}) {
  if (eligibleOrders.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        No orders are currently eligible for cancellation.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {eligibleOrders.map((order) => (
        <button
          key={order.orderNumber}
          type="button"
          disabled={isAgentLoading}
          onClick={() =>
            onResumeV2(
              {
                type: "ORDER_SELECTED",
                capability: "CANCELLATION",
                payload: { orderNumber: order.orderNumber },
              },
              `Order ${order.orderNumber}`
            )
          }
          className="flex w-full items-center justify-between rounded-2xl border border-black/10 bg-[#fbfaf7] px-3 py-2.5 text-left transition hover:border-black/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <div>
            <p className="text-sm font-black text-neutral-950">Order {order.orderNumber}</p>
            <p className="text-xs text-neutral-500">
              {order.orderStatus} · {order.items.length} item{order.items.length === 1 ? "" : "s"}
            </p>
          </div>
          <span className="text-neutral-400">→</span>
        </button>
      ))}
    </div>
  );
}
