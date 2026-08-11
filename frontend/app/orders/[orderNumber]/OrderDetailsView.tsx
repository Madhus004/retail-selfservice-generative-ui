"use client";

import { useRouter } from "next/navigation";
import { PromiseDashboardCanvas } from "@/components/PromiseDashboardCanvas";
import { useAssistant } from "@/components/assistant/AssistantProvider";
import { usePageContext } from "@/lib/page-context";
import type { OrderScenario } from "@/types/order";

export function OrderDetailsView({ order }: { order: OrderScenario }) {
  const router = useRouter();
  const { open, reportWrongDelivery } = useAssistant();

  usePageContext({ page: "ORDER_DETAILS", orderNumber: order.orderNumber });

  return (
    <PromiseDashboardCanvas
      order={order}
      onBackToOrders={() => router.push("/orders")}
      onReportWrongDelivery={(order) => {
        // Hand off to the contextual assistant rather than building a
        // separate full-page claim flow — this is the point of page context.
        open();
        reportWrongDelivery(order);
      }}
    />
  );
}
