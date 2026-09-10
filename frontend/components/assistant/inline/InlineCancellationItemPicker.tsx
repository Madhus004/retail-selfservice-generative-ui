// frontend/components/assistant/inline/InlineCancellationItemPicker.tsx
//
// V2-only. CANCELLATION's item + quantity selection stage — genuinely
// interactive (2026-08 structured-interaction fix). Finds the order the
// backend already resolved (orderNumber) within the eligible-orders list
// already fetched this turn, lets the customer pick items/quantities, and
// submits a structured ITEM_SELECTED resume on confirm — never free text.
"use client";

import { useState } from "react";
import { CheckCircle2, Minus, Plus } from "lucide-react";
import { getItemImage } from "@/lib/item-images";
import type { StructuredSelectionResume } from "@/lib/agent-api-v2";
import type { CancellationEligibleOrder } from "@/types/cancellation";

export function InlineCancellationItemPicker({
  eligibleOrders,
  orderNumber,
  isAgentLoading,
  onResumeV2,
}: {
  eligibleOrders: CancellationEligibleOrder[];
  orderNumber: string | null | undefined;
  isAgentLoading: boolean;
  onResumeV2: (resume: StructuredSelectionResume, userFacingLabel: string) => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, number>>({});

  const order = eligibleOrders.find((candidate) => candidate.orderNumber === orderNumber);

  if (!order) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        Loading order details...
      </div>
    );
  }

  const cancellableItems = order.items.filter((item) => item.cancellableQuantity > 0);
  const selectedLineIds = Object.keys(quantities).filter((id) => quantities[id] > 0);

  const toggleItem = (orderLineId: string) => {
    setQuantities((prev) => {
      if (prev[orderLineId]) {
        const next = { ...prev };
        delete next[orderLineId];
        return next;
      }
      return { ...prev, [orderLineId]: 1 };
    });
  };

  const adjustQuantity = (orderLineId: string, delta: number, max: number) => {
    setQuantities((prev) => {
      const current = prev[orderLineId] ?? 1;
      const next = Math.min(Math.max(current + delta, 1), max);
      return { ...prev, [orderLineId]: next };
    });
  };

  const handleSubmit = () => {
    if (selectedLineIds.length === 0) return;

    onResumeV2(
      {
        type: "ITEM_SELECTED",
        capability: "CANCELLATION",
        payload: {
          selections: selectedLineIds.map((orderLineId) => ({
            orderLineId,
            quantity: quantities[orderLineId],
          })),
        },
      },
      `${selectedLineIds.length} item${selectedLineIds.length === 1 ? "" : "s"} selected`
    );
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {cancellableItems.map((item) => {
          const isSelected = Boolean(quantities[item.orderLineId]);

          return (
            <div
              key={item.orderLineId}
              className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-2.5"
            >
              <label className="flex items-start gap-2.5">
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={isAgentLoading}
                  onChange={() => toggleItem(item.orderLineId)}
                  className="mt-0.5"
                />

                {getItemImage(item.itemName) ? (
                  <img
                    src={getItemImage(item.itemName)}
                    alt=""
                    className="h-10 w-10 shrink-0 rounded-lg object-cover"
                  />
                ) : (
                  <div className="h-10 w-10 shrink-0 rounded-lg bg-neutral-200" />
                )}

                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold text-neutral-900">{item.itemName}</p>
                  <p className="text-xs text-neutral-500">
                    {item.color} · Size {item.size}
                  </p>
                </div>
              </label>

              {isSelected && item.cancellableQuantity > 1 && (
                <div className="mt-2 flex items-center gap-2 pl-6">
                  <span className="text-xs font-bold text-neutral-500">Quantity</span>
                  <button
                    type="button"
                    aria-label={`Decrease quantity for ${item.itemName}`}
                    onClick={() => adjustQuantity(item.orderLineId, -1, item.cancellableQuantity)}
                    disabled={isAgentLoading}
                    className="flex h-6 w-6 items-center justify-center rounded-full border border-black/10 text-neutral-600"
                  >
                    <Minus size={12} />
                  </button>
                  <span className="w-5 text-center text-sm font-bold">
                    {quantities[item.orderLineId]}
                  </span>
                  <button
                    type="button"
                    aria-label={`Increase quantity for ${item.itemName}`}
                    onClick={() => adjustQuantity(item.orderLineId, 1, item.cancellableQuantity)}
                    disabled={isAgentLoading}
                    className="flex h-6 w-6 items-center justify-center rounded-full border border-black/10 text-neutral-600"
                  >
                    <Plus size={12} />
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <button
        type="button"
        onClick={handleSubmit}
        disabled={isAgentLoading || selectedLineIds.length === 0}
        className="flex w-full items-center justify-center gap-2 rounded-full bg-black px-4 py-2.5 text-xs font-black text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
      >
        <CheckCircle2 size={14} />
        Continue
      </button>
    </div>
  );
}
