// frontend/components/assistant/inline/InlineDecomposedReturnItem.tsx
//
// V2-only. RETURNS' item-selection stage (plan section 25: decompose the
// old monolithic cancellation-style wizard into agent-driven turns at
// stage granularity). Genuinely interactive (2026-08 structured-
// interaction fix — originally this was read-only display-only, since no
// structured resume shape existed yet for item selection): checkboxes +
// quantity steppers, submitting a structured ITEM_SELECTED resume on
// confirm — never free text.
"use client";

import { useState } from "react";
import { CheckCircle2, Minus, Plus } from "lucide-react";
import { getItemImage } from "@/lib/item-images";
import type { StructuredSelectionResume } from "@/lib/agent-api-v2";

type ReturnEligibleItem = {
  orderLineId: string;
  itemName: string;
  color: string;
  size: string;
  returnableQuantity: number;
};

type ReturnEligibility = {
  orderNumber?: string;
  eligible?: boolean;
  reason?: string | null;
  returnWindowExpiresAt?: string | null;
  items?: ReturnEligibleItem[];
};

export function InlineDecomposedReturnItem({
  returnEligibility,
  isAgentLoading,
  onResumeV2,
}: {
  returnEligibility?: ReturnEligibility | null;
  isAgentLoading: boolean;
  onResumeV2: (resume: StructuredSelectionResume, userFacingLabel: string) => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, number>>({});

  if (!returnEligibility) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        Checking return eligibility...
      </div>
    );
  }

  if (!returnEligibility.eligible) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        {returnEligibility.reason ?? "This order isn't eligible for a return."}
      </div>
    );
  }

  const items = returnEligibility.items ?? [];
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
        capability: "RETURNS",
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
      <p className="text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
        {returnEligibility.orderNumber
          ? `Order ${returnEligibility.orderNumber} — select items to return`
          : "Select items to return"}
      </p>

      <div className="space-y-2">
        {items.map((item) => {
          const isSelected = Boolean(quantities[item.orderLineId]);

          return (
            <div
              key={item.orderLineId}
              className="rounded-xl border border-black/10 bg-[#fbfaf7] p-2.5"
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
                    {item.color} · Size {item.size} · {item.returnableQuantity} returnable
                  </p>
                </div>
              </label>

              {isSelected && item.returnableQuantity > 1 && (
                <div className="mt-2 flex items-center gap-2 pl-6">
                  <span className="text-xs font-bold text-neutral-500">Quantity</span>
                  <button
                    type="button"
                    aria-label={`Decrease quantity for ${item.itemName}`}
                    onClick={() => adjustQuantity(item.orderLineId, -1, item.returnableQuantity)}
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
                    onClick={() => adjustQuantity(item.orderLineId, 1, item.returnableQuantity)}
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

      {returnEligibility.returnWindowExpiresAt && (
        <p className="text-xs text-neutral-500">
          Return window closes {returnEligibility.returnWindowExpiresAt}
        </p>
      )}

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
