// frontend/components/assistant/inline/InlineCancellationBuilder.tsx
//
// Self-contained multi-step wizard: select order -> select items/quantities
// -> reason -> review -> submit. Panel-native from the start (simple
// checkbox list + stepper, no dashboard-style layout).
"use client";

import { useState } from "react";
import { CheckCircle2, ChevronLeft, Minus, Plus } from "lucide-react";
import { getItemImage } from "@/lib/item-images";
import type {
  CancellationEligibleOrder,
  CancellationLineSelection,
} from "@/types/cancellation";

type Step = "selectOrder" | "selectItems" | "reason" | "review";

const CANCELLATION_REASONS = [
  "Found a better price",
  "Ordered by mistake",
  "No longer needed",
  "Taking too long",
  "Other",
];

export function InlineCancellationBuilder({
  eligibleOrders,
  onSubmit,
}: {
  eligibleOrders: CancellationEligibleOrder[];
  onSubmit: (
    orderNumber: string,
    lineSelections: CancellationLineSelection[],
    reason: string
  ) => void;
}) {
  const [selectedOrder, setSelectedOrder] =
    useState<CancellationEligibleOrder | null>(null);
  const [step, setStep] = useState<Step>("selectOrder");
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [reason, setReason] = useState(CANCELLATION_REASONS[0]);
  const [hasSubmitted, setHasSubmitted] = useState(false);

  if (eligibleOrders.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        No orders are currently eligible for cancellation — orders can only
        be cancelled before they ship.
      </div>
    );
  }

  const selectedLineIds = Object.keys(quantities).filter(
    (id) => quantities[id] > 0
  );

  const handleSelectOrder = (order: CancellationEligibleOrder) => {
    setSelectedOrder(order);
    setQuantities({});
    setStep("selectItems");
  };

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

  const handleBack = () => {
    if (step === "selectItems") setStep("selectOrder");
    else if (step === "reason") setStep("selectItems");
    else if (step === "review") setStep("reason");
  };

  const handleSubmit = () => {
    if (!selectedOrder || hasSubmitted) return;

    const lineSelections: CancellationLineSelection[] = selectedLineIds.map(
      (orderLineId) => ({ orderLineId, quantity: quantities[orderLineId] })
    );

    setHasSubmitted(true);
    onSubmit(selectedOrder.orderNumber, lineSelections, reason);
  };

  return (
    <div className="rounded-2xl border border-black/10 bg-white p-3">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
          Cancel an order
        </p>

        {step !== "selectOrder" && !hasSubmitted && (
          <button
            onClick={handleBack}
            className="flex items-center gap-1 text-xs font-bold text-neutral-500 hover:text-neutral-800"
          >
            <ChevronLeft size={14} /> Back
          </button>
        )}
      </div>

      {step === "selectOrder" && (
        <div className="space-y-2">
          {eligibleOrders.map((order) => (
            <button
              key={order.orderNumber}
              onClick={() => handleSelectOrder(order)}
              className="flex w-full items-center justify-between rounded-2xl border border-black/10 bg-[#fbfaf7] px-3 py-2.5 text-left transition hover:border-black/30"
            >
              <div>
                <p className="text-sm font-black text-neutral-950">
                  Order {order.orderNumber}
                </p>
                <p className="text-xs text-neutral-500">
                  {order.orderStatus} · {order.items.length} item
                  {order.items.length === 1 ? "" : "s"}
                </p>
              </div>
              <span className="text-neutral-400">→</span>
            </button>
          ))}
        </div>
      )}

      {step === "selectItems" && selectedOrder && (
        <div className="space-y-3">
          <p className="text-xs text-neutral-500">
            Select the items you&apos;d like to cancel from order{" "}
            {selectedOrder.orderNumber}.
          </p>

          <div className="space-y-2">
            {selectedOrder.items.map((item) => {
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
                      <p className="truncate text-sm font-bold text-neutral-900">
                        {item.itemName}
                      </p>
                      <p className="text-xs text-neutral-500">
                        {item.color} · Size {item.size}
                      </p>
                    </div>
                  </label>

                  {isSelected && item.cancellableQuantity > 1 && (
                    <div className="mt-2 flex items-center gap-2 pl-6">
                      <span className="text-xs font-bold text-neutral-500">
                        Quantity
                      </span>
                      <button
                        onClick={() =>
                          adjustQuantity(
                            item.orderLineId,
                            -1,
                            item.cancellableQuantity
                          )
                        }
                        className="flex h-6 w-6 items-center justify-center rounded-full border border-black/10 text-neutral-600"
                      >
                        <Minus size={12} />
                      </button>
                      <span className="w-5 text-center text-sm font-bold">
                        {quantities[item.orderLineId]}
                      </span>
                      <button
                        onClick={() =>
                          adjustQuantity(
                            item.orderLineId,
                            1,
                            item.cancellableQuantity
                          )
                        }
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
            onClick={() => setStep("reason")}
            disabled={selectedLineIds.length === 0}
            className="w-full rounded-full bg-black px-4 py-2.5 text-xs font-black text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
          >
            Continue
          </button>
        </div>
      )}

      {step === "reason" && (
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-bold text-neutral-700">
              Why are you cancelling?
            </span>
            <select
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="w-full rounded-xl border border-black/10 bg-[#fbfaf7] p-2.5 text-xs font-bold text-neutral-700 outline-none focus:border-black/30"
            >
              {CANCELLATION_REASONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <button
            onClick={() => setStep("review")}
            className="w-full rounded-full bg-black px-4 py-2.5 text-xs font-black text-white transition hover:bg-neutral-800"
          >
            Review cancellation
          </button>
        </div>
      )}

      {step === "review" && selectedOrder && (
        <div className="space-y-3">
          <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
              Order {selectedOrder.orderNumber}
            </p>

            <div className="mt-2 space-y-1.5">
              {selectedLineIds.map((orderLineId) => {
                const item = selectedOrder.items.find(
                  (candidate) => candidate.orderLineId === orderLineId
                );
                if (!item) return null;

                return (
                  <p key={orderLineId} className="text-sm text-neutral-800">
                    {quantities[orderLineId]} × {item.itemName} (
                    {item.color}, {item.size})
                  </p>
                );
              })}
            </div>

            <p className="mt-2 text-xs text-neutral-500">Reason: {reason}</p>
          </div>

          <button
            onClick={handleSubmit}
            disabled={hasSubmitted}
            className="flex w-full items-center justify-center gap-2 rounded-full bg-black px-4 py-2.5 text-xs font-black text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
          >
            <CheckCircle2 size={14} />
            {hasSubmitted ? "Submitting..." : "Confirm cancellation"}
          </button>
        </div>
      )}
    </div>
  );
}
