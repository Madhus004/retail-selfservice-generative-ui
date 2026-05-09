// frontend/components/OrderSelectionCanvas.tsx

import { ArrowRight, Loader2, Package } from "lucide-react";
import type { OrderScenario } from "@/types/order";

export function OrderSelectionCanvas({
  orders,
  isAgentLoading,
  loadingOrderNumber,
  onSelectOrder,
}: {
  orders: OrderScenario[];
  isAgentLoading: boolean;
  loadingOrderNumber: string | null;
  onSelectOrder: (order: OrderScenario) => void;
}) {
  return (
    <div className="min-h-full rounded-[1.5rem] bg-white p-8">
      <div className="mb-8 flex items-start justify-between gap-6">
        <div>
          <p className="mb-3 text-xs font-black uppercase tracking-[0.28em] text-neutral-400">
            Where is my order?
          </p>
          <h2 className="text-4xl font-black tracking-[-0.055em] text-neutral-950">
            Select an order to track.
          </h2>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-neutral-600">
            Uni found recent Unicorn orders that may need delivery support.
            Select one to view package-level promise tracking, delivery proof,
            and available service actions.
          </p>
        </div>

        <div className="hidden rounded-full border border-black/10 bg-neutral-50 px-4 py-2 text-sm font-bold text-neutral-600 md:flex">
          Demo customer: Demo Customer
        </div>
      </div>

      {isAgentLoading && orders.length === 0 && (
        <div className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-6">
          <div className="flex items-center gap-3 text-sm font-bold text-neutral-700">
            <Loader2 className="animate-spin" size={18} />
            Uni is retrieving recent orders...
          </div>
        </div>
      )}

      {!isAgentLoading && orders.length === 0 && (
        <div className="rounded-3xl border border-dashed border-black/20 bg-neutral-50 p-6">
          <p className="text-sm leading-6 text-neutral-600">
            No recent orders are loaded yet. Ask Uni “Where is my order?” to
            retrieve order options.
          </p>
        </div>
      )}

      {orders.length > 0 && (
        <div className="grid gap-4">
          {orders.map((order) => {
            const isThisOrderLoading =
              loadingOrderNumber === order.orderNumber;

            return (
              <button
                key={order.orderNumber}
                onClick={() => onSelectOrder(order)}
                disabled={isAgentLoading}
                className="group rounded-3xl border border-black/10 bg-[#fbfaf7] p-5 text-left transition hover:-translate-y-0.5 hover:border-black/30 hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-60"
              >
                <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-start gap-4">
                    <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-black text-white">
                      <Package size={22} />
                    </div>

                    <div>
                      <div className="flex flex-wrap items-center gap-3">
                        <h3 className="text-xl font-black tracking-[-0.04em]">
                          Order {order.orderNumber}
                        </h3>
                        <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-neutral-600 ring-1 ring-black/10">
                          {order.status}
                        </span>
                      </div>

                      <p className="mt-2 text-sm text-neutral-500">
                        Placed {order.date} • {order.items}
                      </p>

                      <p className="mt-2 text-sm font-bold text-neutral-800">
                        {order.promise}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-sm font-black">
                    {isThisOrderLoading ? "Loading..." : "Review order"}
                    {isThisOrderLoading ? (
                      <Loader2 className="animate-spin" size={18} />
                    ) : (
                      <ArrowRight
                        className="transition group-hover:translate-x-1"
                        size={18}
                      />
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}