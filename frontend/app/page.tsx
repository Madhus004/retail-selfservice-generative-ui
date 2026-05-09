// frontend/app/page.tsx
"use client";

import { useState } from "react";
import { useCopilotAction } from "@copilotkit/react-core";
import { RetailHeader } from "@/components/RetailHeader";
import { SupportWorkspace } from "@/components/SupportWorkspace";
import { sendAgentMessage, streamAgentMessage } from "@/lib/agent-api";
import type {
  A2UIComponent,
  AgentChatResponse,
  AgentStep,
  AgentUIMode,
  StreamedAgentEvent,
} from "@/lib/agent-api";
import type {
  ClaimSubmissionResult,
  OrderScenario,
  PromiseMilestone,
  PromiseTone,
  ServiceRecovery,
  WrongDeliveryClaimDraft,
} from "@/types/order";

type BackendRecentOrder = {
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
  promisedDelivery: "Met" | "At risk" | "Missed";
};

type BackendDashboard = {
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

function formatDate(value?: string | null) {
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

function formatDateTime(value?: string | null) {
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

function formatMoney(value: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(value);
}

function getPromiseTone(status: "Met" | "At risk" | "Missed"): PromiseTone {
  if (status === "Met") return "success";
  if (status === "At risk") return "warning";
  return "danger";
}

function mapRecentOrderToScenario(order: BackendRecentOrder): OrderScenario {
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

function mapDashboardToScenario(dashboard: BackendDashboard): OrderScenario {
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

export default function Home() {
  const [canvasMode, setCanvasMode] = useState<AgentUIMode>("welcome");
  const [a2uiComponents, setA2uiComponents] = useState<A2UIComponent[]>([
    {
      type: "welcome",
      props: {},
    },
  ]);
  const [orders, setOrders] = useState<OrderScenario[]>([]);
  const [selectedOrder, setSelectedOrder] = useState<OrderScenario | null>(null);
  const [isAgentLoading, setIsAgentLoading] = useState(false);
  const [loadingOrderNumber, setLoadingOrderNumber] = useState<string | null>(
    null
  );
  const [agentProgressSteps, setAgentProgressSteps] = useState<AgentStep[]>([]);
  const [claimResult, setClaimResult] = useState<ClaimSubmissionResult | null>(
    null
  );

  const applyA2UIState = (
    uiMode: AgentUIMode,
    components?: A2UIComponent[]
  ) => {
    setCanvasMode(uiMode);
    setA2uiComponents(
      components && components.length > 0 ? components : [{ type: uiMode }]
    );
  };

  const applyAgentResponse = (
    response: AgentChatResponse,
    fallbackOrder?: OrderScenario
  ) => {
    const backendOrders =
      (response.uiState.canvasData?.orders as BackendRecentOrder[]) ?? [];

    if (response.uiState.uiMode === "orderSelection") {
      setOrders(backendOrders.map(mapRecentOrderToScenario));
      setSelectedOrder(null);
      setClaimResult(null);
      applyA2UIState(response.uiState.uiMode, response.uiState.a2ui);
      return;
    }

    if (response.uiState.uiMode === "promiseDashboard") {
      const selectedOrderData = response.uiState.canvasData
        ?.selectedOrder as BackendDashboard;

      const mappedOrder = {
        ...mapDashboardToScenario(selectedOrderData),
        customerSummary: response.message,
      };

      setSelectedOrder(mappedOrder);
      setClaimResult(null);
      applyA2UIState(response.uiState.uiMode, response.uiState.a2ui);
      return;
    }

    if (response.uiState.uiMode === "wrongDeliveryClaim") {
      const selectedOrderData = response.uiState.canvasData
        ?.selectedOrder as BackendDashboard | undefined;

      const mappedOrder =
        selectedOrderData && Object.keys(selectedOrderData).length > 0
          ? {
              ...mapDashboardToScenario(selectedOrderData),
              customerSummary: response.message,
            }
          : fallbackOrder
            ? {
                ...fallbackOrder,
                customerSummary: response.message,
              }
            : selectedOrder;

      setSelectedOrder(mappedOrder ?? null);
      setClaimResult(null);
      applyA2UIState(response.uiState.uiMode, response.uiState.a2ui);
      return;
    }

    applyA2UIState(response.uiState.uiMode, response.uiState.a2ui);
  };

  const handleStreamEvent = (event: StreamedAgentEvent) => {
    if (
      event.type === "RUN_STARTED" ||
      event.type === "STATE_DELTA" ||
      event.type === "RUN_FINISHED" ||
      event.type === "ERROR"
    ) {
      setAgentProgressSteps((prev) => [
        ...prev,
        {
          label: event.label,
          status: event.status,
        },
      ]);
    }
  };

  const runStreamingAgentRequest = async (
    message: string,
    fallbackOrder?: OrderScenario
  ) => {
    setIsAgentLoading(true);
    setLoadingOrderNumber(null);
    setAgentProgressSteps([]);
    setClaimResult(null);

    try {
      const finalResponse = await streamAgentMessage({
        message,
        onEvent: (event) => {
          handleStreamEvent(event);
        },
      });

      if (finalResponse) {
        applyAgentResponse(finalResponse, fallbackOrder);
        return finalResponse.message;
      }

      const fallbackResponse = await sendAgentMessage(message);
      applyAgentResponse(fallbackResponse, fallbackOrder);
      return fallbackResponse.message;
    } catch (error) {
      console.error(error);
      return "I’m sorry, I couldn’t reach the Uni support agent right now. Please try again in a moment.";
    } finally {
      setIsAgentLoading(false);
      setLoadingOrderNumber(null);

      window.setTimeout(() => {
        setAgentProgressSteps([]);
      }, 700);
    }
  };

  useCopilotAction({
    name: "askUni",
    description:
      "Use this for any Unicorn Apparel customer support request about order tracking, delivery promise status, late delivery, weather delay, delivery proof, wrong delivery, claims, refunds, coupons, or service recovery. This action updates the main support workspace canvas using LangGraph, AG-UI-style progress events, and A2UI.",
    parameters: [
      {
        name: "message",
        type: "string",
        description:
          "The customer's full support request, for example: Where is my order? Track U-1002. My order U-1001 says delivered but I do not see it.",
        required: true,
      },
    ],
    handler: async ({ message }: { message: string }) => {
      return runStreamingAgentRequest(message);
    },
  });

  const handleWhereIsMyOrder = async () => {
    setSelectedOrder(null);
    setLoadingOrderNumber(null);
    setClaimResult(null);

    await runStreamingAgentRequest("Where is my order?");
  };

  const handleSelectOrder = async (order: OrderScenario) => {
    setSelectedOrder(null);
    setClaimResult(null);
    applyA2UIState("orderSelection", [{ type: "orderSelection" }]);
    setLoadingOrderNumber(order.orderNumber);

    await runStreamingAgentRequest(`Track ${order.orderNumber}`, order);
  };

  const handleReportWrongDelivery = async (order: OrderScenario) => {
    const message = `My order ${order.orderNumber} says delivered but I do not see it at my address`;

    await runStreamingAgentRequest(message, order);
  };

  const handleSubmitWrongDeliveryClaim = (claim: WrongDeliveryClaimDraft) => {
    const claimId = `CLAIM-${claim.orderNumber.replace("-", "")}-${Date.now()
      .toString()
      .slice(-4)}`;

    const confirmationMessage =
      "Thanks — we submitted your wrong-delivery claim. Our service team will investigate and provide an update within 1–2 days.";

    setClaimResult({
      claimId,
      orderNumber: claim.orderNumber,
      status: "submitted",
      submittedAt: new Date().toISOString(),
      slaMessage: confirmationMessage,
    });

    applyA2UIState("claimSubmitted", [
      {
        type: "claimSubmitted",
        props: {
          dataKey: "claimResult",
          claimId,
        },
      },
    ]);
  };

  const handleBackToOrders = () => {
    setSelectedOrder(null);
    setLoadingOrderNumber(null);
    setClaimResult(null);
    setAgentProgressSteps([]);
    applyA2UIState("orderSelection", [{ type: "orderSelection" }]);
  };

  const handleBackToDashboard = () => {
    setAgentProgressSteps([]);
    applyA2UIState("promiseDashboard", [{ type: "promiseDashboard" }]);
  };

  return (
    <main className="min-h-screen bg-[#f7f3ed] text-[#111111]">
      <RetailHeader />

      <section className="mx-auto max-w-[1700px] px-8 pb-12 pt-8">
        <div className="mb-6 max-w-5xl">
          <p className="mb-3 text-xs font-bold uppercase tracking-[0.28em] text-neutral-500">
            Unicorn Apparel Support
          </p>
          <h1 className="max-w-5xl text-5xl font-black tracking-[-0.055em] text-neutral-950 md:text-6xl">
            AI Support That Goes Beyond Chat.
          </h1>
          <p className="mt-5 max-w-3xl text-base leading-7 text-neutral-600">
            Uni is Unicorn’s AI self-service associate, combining conversation
            with a dynamic support workspace for order tracking, delivery
            issues, returns, and shopping assistance.
          </p>
        </div>

        <SupportWorkspace
          canvasMode={canvasMode}
          a2uiComponents={a2uiComponents}
          selectedOrder={selectedOrder}
          orders={orders}
          isAgentLoading={isAgentLoading}
          loadingOrderNumber={loadingOrderNumber}
          agentProgressSteps={agentProgressSteps}
          claimResult={claimResult}
          onWhereIsMyOrder={handleWhereIsMyOrder}
          onSelectOrder={handleSelectOrder}
          onReportWrongDelivery={handleReportWrongDelivery}
          onSubmitWrongDeliveryClaim={handleSubmitWrongDeliveryClaim}
          onBackToOrders={handleBackToOrders}
          onBackToDashboard={handleBackToDashboard}
        />
      </section>
    </main>
  );
}