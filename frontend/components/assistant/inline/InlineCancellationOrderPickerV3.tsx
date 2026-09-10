// frontend/components/assistant/inline/InlineCancellationOrderPickerV3.tsx
//
// V3-only. CANCELLATION's order-selection stage (V3's CancellationOrderPicker
// a2ui type). Adapted from InlineCancellationOrderPicker (V2) — same UI,
// but the resume payload carries no "capability" field, since V3's
// ask_customer_node doesn't validate one (agent/v3/graph.py).
"use client";

import type { StructuredSelectionResumeV3 } from "@/lib/agent-api-v3";
import type { CancellationEligibleOrder } from "@/types/cancellation";

export function InlineCancellationOrderPickerV3({
  eligibleOrders,
  isAgentLoading,
  onResumeV3,
}: {
  eligibleOrders: CancellationEligibleOrder[];
  isAgentLoading: boolean;
  onResumeV3: (resume: StructuredSelectionResumeV3, userFacingLabel: string) => void;
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
            onResumeV3(
              { type: "ORDER_SELECTED", payload: { orderNumber: order.orderNumber } },
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
