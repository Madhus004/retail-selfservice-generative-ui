// frontend/components/assistant/inline/InlineOrderList.tsx
//
// Panel-native replacement for OrderSelectionCanvas. The "My order isn't
// listed" quick action is no longer hardcoded here — it comes from the
// backend's deterministic suggestedReplies for this turn, rendered
// generically by AssistantTranscript.

import { Loader2 } from "lucide-react";
import { InlineOrderCard } from "@/components/assistant/inline/InlineOrderCard";
import type { OrderScenario } from "@/types/order";

export function InlineOrderList({
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
  if (isAgentLoading && orders.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-black/10 bg-[#fbfaf7] px-3 py-2.5 text-sm text-neutral-600">
        <Loader2 size={14} className="animate-spin" />
        Retrieving recent orders...
      </div>
    );
  }

  if (!isAgentLoading && orders.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-black/20 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-600">
        No recent orders loaded yet.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {orders.map((order) => (
        <InlineOrderCard
          key={order.orderNumber}
          order={order}
          isLoading={loadingOrderNumber === order.orderNumber}
          disabled={isAgentLoading}
          onSelect={() => onSelectOrder(order)}
        />
      ))}
    </div>
  );
}
