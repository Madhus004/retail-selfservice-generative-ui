// frontend/app/orders/[orderNumber]/page.tsx
//
// Full-page order details. Reuses PromiseDashboardCanvas as-is — see
// CLAUDE.md / plan Phase 1D. Reporting a delivery issue here opens the
// assistant panel and hands off to it, demonstrating page-context awareness
// rather than duplicating a claim flow on the page itself.

import { notFound } from "next/navigation";
import { AGENT_API_BASE_URL } from "@/lib/agent-api";
import { mapDashboardToScenario, type BackendDashboard } from "@/lib/map-backend-order";
import { OrderDetailsView } from "./OrderDetailsView";

export default async function OrderDetailsPage({
  params,
}: {
  params: Promise<{ orderNumber: string }>;
}) {
  const { orderNumber } = await params;

  const response = await fetch(
    `${AGENT_API_BASE_URL}/orders/${orderNumber}/promise-dashboard`,
    { cache: "no-store" }
  );

  if (response.status === 404) {
    notFound();
  }

  const dashboard: BackendDashboard = await response.json();
  const order = mapDashboardToScenario(dashboard);

  return (
    <main className="min-h-screen bg-[#f7f3ed] px-8 py-10">
      <div className="mx-auto max-w-[1400px]">
        <OrderDetailsView order={order} />
      </div>
    </main>
  );
}
