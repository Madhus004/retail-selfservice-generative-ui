// frontend/app/orders/page.tsx
//
// Full-page order history. Reuses OrderSelectionCanvas as-is — its
// dashboard-style layout, built for a 70%-width canvas, is exactly right for
// a dedicated full-width page (see CLAUDE.md / plan Phase 1D).

import { AGENT_API_BASE_URL } from "@/lib/agent-api";
import { mapRecentOrderToScenario, type BackendRecentOrder } from "@/lib/map-backend-order";
import { OrderHistoryView } from "./OrderHistoryView";

export const metadata = {
  title: "Your Orders — Unicorn Apparel",
};

export default async function OrdersPage() {
  const response = await fetch(
    `${AGENT_API_BASE_URL}/customers/demo/recent-orders`,
    { cache: "no-store" }
  );

  const data: { orders: BackendRecentOrder[] } = await response.json();
  const orders = data.orders.map(mapRecentOrderToScenario);

  return (
    <main className="min-h-screen bg-[#f7f3ed] px-8 py-10">
      <div className="mx-auto max-w-[1400px]">
        <OrderHistoryView orders={orders} />
      </div>
    </main>
  );
}
