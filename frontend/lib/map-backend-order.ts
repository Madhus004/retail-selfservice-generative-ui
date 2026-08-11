// frontend/lib/map-backend-order.ts
//
// Maps raw backend response shapes (agent/tools.py's get_recent_orders /
// get_order_promise_dashboard, as forwarded through agent/main.py's uiState.canvasData)
// into the frontend's OrderScenario view model consumed by the canvas components.

import type {
  OrderScenario,
  PromiseMilestone,
  PromiseTone,
  ServiceRecovery,
} from "@/types/order";

export type BackendRecentOrder = {
  orderNumber: string;
  customerName: string;
  orderDate: string;
  orderStatus: string;
  orderTotal: number;
  currency: string;
  itemCount: number;
  packageCount: number;
  summary: string;
  originalPromiseDate: string;
  promisedDelivery: "Met" | "At risk" | "Missed" | "Processing";
};

export type BackendDashboard = {
  customer: {
    name: string;
  };
  order: {
    orderNumber: string;
    orderDate: string;
    orderStatus: string;
    originalPromiseDate: string;
    currency: string;
    orderTotal: number;
  };
  summary: {
    customerMessage: string;
    overallPromiseStatus: "Met" | "At risk" | "Missed";
    packageCount: number;
    itemCount: number;
    hasDeliveryProof: boolean;
    hasServiceRecovery: boolean;
  };
  packages: {
    packageId: string;
    packageNumber: number;
    carrier: string;
    trackingNumber: string;
    packageStatus: string;
    shippedAt?: string | null;
    actualDeliveredAt?: string | null;
    estimatedDeliveryAt?: string | null;
    carrierTrackingUrl: string;
    items: {
      itemName: string;
      color: string;
      size: string;
      packageQuantity: number;
      quantity: number;
      price: number;
      imageGradient?: string;
    }[];
    trackingEvents: {
      eventLabel: string;
      eventTimestamp: string;
      eventType: string;
    }[];
    promise: {
      originalPromisedAt: string;
      currentEstimatedAt?: string | null;
      actualDeliveredAt?: string | null;
      promiseResult: "met" | "at_risk" | "missed";
      promiseReasonCode?: string;
    };
    deliveryProof?: {
      deliveredAt: string;
      locationNote: string;
      proofImageUrl?: string;
      proofAvailable: boolean;
    } | null;
    serviceRecoveryActions: {
      actionType: string;
      title: string;
      description: string;
      couponCode?: string | null;
      refundAmount?: number | null;
      status: string;
    }[];
  }[];
  serviceRecoveryActions: {
    actionType: string;
    title: string;
    description: string;
    couponCode?: string | null;
    refundAmount?: number | null;
    status: string;
  }[];
};

export function formatDate(value?: string | null) {
  if (!value) return "Not available";

  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date(year, month - 1, day));
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value?: string | null) {
  if (!value) return "Not available";

  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return formatDate(value);
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function formatMoney(value: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(value);
}

export function getPromiseTone(
  status: "Met" | "At risk" | "Missed" | "Processing"
): PromiseTone {
  if (status === "Met") return "success";
  if (status === "At risk") return "warning";
  if (status === "Processing") return "neutral";
  return "danger";
}

export function mapRecentOrderToScenario(order: BackendRecentOrder): OrderScenario {
  return {
    orderNumber: order.orderNumber,
    status: order.orderStatus,
    promise: `Promised delivery: ${order.promisedDelivery}`,
    date: formatDate(order.orderDate),
    items: `${order.itemCount} item${order.itemCount === 1 ? "" : "s"} • ${
      order.packageCount
    } package${order.packageCount === 1 ? "" : "s"}`,
    customerName: order.customerName,
    orderPromiseSummary: `Original promise: ${formatDate(
      order.originalPromiseDate
    )}`,
    promiseStatusLabel: order.promisedDelivery,
    promiseStatusTone: getPromiseTone(order.promisedDelivery),
    customerSummary:
      "Select this order and Uni will review the latest package-level promise status.",
    packages: [],
  };
}

function buildMilestones(
  trackingEvents: BackendDashboard["packages"][number]["trackingEvents"],
  originalPromisedAt: string,
  promiseResult: "met" | "at_risk" | "missed"
): PromiseMilestone[] {
  const filteredEvents = trackingEvents.filter(
    (event) =>
      event.eventType !== "label_created" &&
      event.eventLabel.toLowerCase() !== "order placed"
  );

  const timelineItems = [
    ...filteredEvents.map((event) => {
      let tone: PromiseMilestone["tone"] = "neutral";

      if (event.eventType === "shipped") {
        tone = "success";
      }

      if (event.eventType === "delivered") {
        tone = promiseResult === "missed" ? "danger" : "success";
      }

      if (event.eventType === "weather_delay") {
        tone = "warning";
      }

      return {
        label: event.eventLabel,
        date: formatDateTime(event.eventTimestamp),
        rawDate: event.eventTimestamp,
        tone,
      };
    }),
    {
      label: "Original promise",
      date: formatDate(originalPromisedAt),
      rawDate: originalPromisedAt,
      tone: "promise" as PromiseMilestone["tone"],
    },
  ];

  const sortedItems = timelineItems.sort(
    (a, b) => new Date(a.rawDate).getTime() - new Date(b.rawDate).getTime()
  );

  const positions = [18, 42, 66, 84];

  return sortedItems.slice(0, 4).map((item, index) => ({
    label: item.label,
    date: item.date,
    position: positions[index],
    tone: item.tone,
  }));
}

function buildServiceRecovery(
  dashboard: BackendDashboard
): ServiceRecovery | undefined {
  const actions = dashboard.serviceRecoveryActions;

  if (!actions.length) {
    return undefined;
  }

  const refundAction = actions.find(
    (action) => action.actionType === "shipping_refund"
  );
  const couponAction = actions.find((action) => action.actionType === "coupon");

  if (refundAction && couponAction?.couponCode) {
    return {
      title: "We’ve made this right",
      description:
        "We refunded your shipping fee and added an offer for your next Unicorn order.",
      badge: "Shipping refunded",
      secondaryBadge: couponAction.couponCode,
      tone: "refund",
    };
  }

  if (couponAction?.couponCode) {
    return {
      title: "A little something for the delay",
      description: couponAction.description,
      badge: couponAction.couponCode,
      tone: "coupon",
    };
  }

  return {
    title: "Service action available",
    description: actions[0].description,
    badge: actions[0].title,
    tone: "info",
  };
}

export function mapDashboardToScenario(dashboard: BackendDashboard): OrderScenario {
  const status = dashboard.summary.overallPromiseStatus;

  return {
    orderNumber: dashboard.order.orderNumber,
    status: dashboard.order.orderStatus,
    promise: `Promised delivery: ${status}`,
    date: formatDate(dashboard.order.orderDate),
    items: `${dashboard.summary.itemCount} item${
      dashboard.summary.itemCount === 1 ? "" : "s"
    } • ${dashboard.summary.packageCount} package${
      dashboard.summary.packageCount === 1 ? "" : "s"
    }`,
    customerName: dashboard.customer.name,
    orderPromiseSummary: `Original promise: ${formatDate(
      dashboard.order.originalPromiseDate
    )}`,
    promiseStatusLabel: status,
    promiseStatusTone: getPromiseTone(status),
    customerSummary: dashboard.summary.customerMessage,
    serviceRecovery: buildServiceRecovery(dashboard),
    packages: dashboard.packages.map((shipmentPackage) => {
      const packagePromiseResult =
        shipmentPackage.promise.promiseResult === "at_risk"
          ? "At risk"
          : shipmentPackage.promise.promiseResult === "missed"
            ? "Missed"
            : "Met";

      const actualOrEstimatedRawDate =
        shipmentPackage.actualDeliveredAt ||
        shipmentPackage.estimatedDeliveryAt ||
        shipmentPackage.promise.currentEstimatedAt ||
        null;

      return {
        packageNumber: shipmentPackage.packageNumber,
        trackingNumber: shipmentPackage.trackingNumber,
        carrier: shipmentPackage.carrier,
        status: shipmentPackage.packageStatus,
        promisedDeliveryResult: packagePromiseResult,
        promisedDelivery: formatDate(shipmentPackage.promise.originalPromisedAt),
        actualOrEstimatedDelivery: actualOrEstimatedRawDate
          ? formatDateTime(actualOrEstimatedRawDate)
          : "Not available",
        fullTrackingUrl: shipmentPackage.carrierTrackingUrl,
        items: shipmentPackage.items.map((item) => ({
          itemName: item.itemName,
          color: item.color,
          size: item.size,
          qty: item.packageQuantity ?? item.quantity,
          price: formatMoney(item.price, dashboard.order.currency),
          imageGradient: item.imageGradient ?? "from-neutral-100 to-neutral-300",
        })),
        milestones: buildMilestones(
          shipmentPackage.trackingEvents,
          shipmentPackage.promise.originalPromisedAt,
          shipmentPackage.promise.promiseResult
        ),
        deliveryProof:
          shipmentPackage.deliveryProof?.proofAvailable === true
            ? {
                deliveredAt: formatDateTime(
                  shipmentPackage.deliveryProof.deliveredAt
                ),
                locationNote: shipmentPackage.deliveryProof.locationNote,
                imageDescription: `Delivery proof photo — ${shipmentPackage.deliveryProof.locationNote}`,
              }
            : undefined,
      };
    }),
  };
}
