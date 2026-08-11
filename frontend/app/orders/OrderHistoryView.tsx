"use client";

import { useRouter } from "next/navigation";
import { OrderSelectionCanvas } from "@/components/OrderSelectionCanvas";
import { usePageContext } from "@/lib/page-context";
import type { OrderScenario } from "@/types/order";

export function OrderHistoryView({ orders }: { orders: OrderScenario[] }) {
  const router = useRouter();

  usePageContext({ page: "ORDER_HISTORY" });

  return (
    <OrderSelectionCanvas
      orders={orders}
      isAgentLoading={false}
      loadingOrderNumber={null}
      onSelectOrder={(order) => router.push(`/orders/${order.orderNumber}`)}
    />
  );
}
