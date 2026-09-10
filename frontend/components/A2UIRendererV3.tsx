// frontend/components/A2UIRendererV3.tsx
//
// V3's own renderer — a sibling to A2UIRenderer.tsx (V1/V2), never a
// replacement. V3's a2ui[] is an ORDERED LIST of composable primitives
// (agent/v3/ui/catalog.py), not "pick the one primary component": a
// handful of types are PRIMARY (screen-anchoring — decide what this
// component renders as the main card) and the rest are SUPPLEMENTAL,
// curating what shows alongside it. This renderer honors that by finding
// the primary type, then passing which supplemental types were actually
// proposed down to the component that knows how to show them
// (InlineOrderSummaryCardV3 — StatusPill/TrackingTimeline/
// DeliveryProofCard/ServiceRecoveryBanner render as sections within it).
"use client";

import type { ReactNode } from "react";
import { InlineCancellationItemPickerV3 } from "@/components/assistant/inline/InlineCancellationItemPickerV3";
import { InlineCancellationOrderPickerV3 } from "@/components/assistant/inline/InlineCancellationOrderPickerV3";
import { InlineConfirmationCardV3 } from "@/components/assistant/inline/InlineConfirmationCardV3";
import { InlineOrderList } from "@/components/assistant/inline/InlineOrderList";
import { InlineOrderSummaryCardV3 } from "@/components/assistant/inline/InlineOrderSummaryCardV3";
import { InlineReturnItemPickerV3 } from "@/components/assistant/inline/InlineReturnItemPickerV3";
import { InlineReturnMethodPromptV3 } from "@/components/assistant/inline/InlineReturnMethodPromptV3";
import { InlineReturnReasonPromptV3 } from "@/components/assistant/inline/InlineReturnReasonPromptV3";
import { InlineWelcome } from "@/components/assistant/inline/InlineWelcome";
import type {
  A2UIComponentV3,
  ConfirmationResumeV3,
  StructuredSelectionResumeV3,
  V3ComponentType,
} from "@/lib/agent-api-v3";
import type { CancellationEligibleOrder } from "@/types/cancellation";
import type { OrderScenario } from "@/types/order";

const PRIMARY_COMPONENT_TYPES = [
  "Welcome",
  "OrderListPicker",
  "OrderSummaryCard",
  "CancellationOrderPicker",
  "CancellationItemPicker",
  "ConfirmationCard",
  "ReturnItemPicker",
  "ReturnReasonPrompt",
  "ReturnMethodPrompt",
] as const;

type PrimaryComponentType = (typeof PRIMARY_COMPONENT_TYPES)[number];

function isPrimaryComponentType(type: V3ComponentType): type is PrimaryComponentType {
  return (PRIMARY_COMPONENT_TYPES as readonly string[]).includes(type);
}

type A2UIRendererV3Props = {
  components: A2UIComponentV3[];
  orders: OrderScenario[];
  selectedOrder: OrderScenario | null;
  eligibleOrders: CancellationEligibleOrder[];
  returnEligibleOrders: CancellationEligibleOrder[];
  returnEligibility: Record<string, unknown> | null;
  returnReasonOptions?: string[];
  orderNumber?: string | null;
  isAgentLoading: boolean;
  loadingOrderNumber: string | null;
  onSelectOrder: (order: OrderScenario) => void;
  onResumeV3: (resume: StructuredSelectionResumeV3 | ConfirmationResumeV3, userFacingLabel: string) => void;
};

export function A2UIRendererV3({
  components,
  orders,
  selectedOrder,
  eligibleOrders,
  returnEligibleOrders,
  returnEligibility,
  returnReasonOptions,
  orderNumber,
  isAgentLoading,
  loadingOrderNumber,
  onSelectOrder,
  onResumeV3,
}: A2UIRendererV3Props) {
  const primary =
    components.find((component) => isPrimaryComponentType(component.type)) ?? null;
  const primaryType: PrimaryComponentType =
    primary && isPrimaryComponentType(primary.type) ? primary.type : "Welcome";

  const supplementalTypes = components
    .map((component) => component.type)
    .filter((type) => type !== primaryType);

  let body: ReactNode;

  if (primaryType === "CancellationOrderPicker") {
    body = (
      <InlineCancellationOrderPickerV3
        eligibleOrders={eligibleOrders}
        isAgentLoading={isAgentLoading}
        onResumeV3={onResumeV3}
      />
    );
  } else if (primaryType === "CancellationItemPicker") {
    body = (
      <InlineCancellationItemPickerV3
        eligibleOrders={eligibleOrders}
        orderNumber={orderNumber}
        isAgentLoading={isAgentLoading}
        onResumeV3={onResumeV3}
      />
    );
  } else if (primaryType === "ReturnItemPicker") {
    body = (
      <InlineReturnItemPickerV3
        returnEligibility={returnEligibility}
        isAgentLoading={isAgentLoading}
        onResumeV3={onResumeV3}
      />
    );
  } else if (primaryType === "ReturnReasonPrompt") {
    body = (
      <InlineReturnReasonPromptV3
        reasonOptions={returnReasonOptions ?? []}
        isAgentLoading={isAgentLoading}
        onResumeV3={onResumeV3}
      />
    );
  } else if (primaryType === "ReturnMethodPrompt") {
    body = (
      <InlineReturnMethodPromptV3
        returnEligibility={returnEligibility as { returnMethods?: string[] } | null}
        isAgentLoading={isAgentLoading}
        onResumeV3={onResumeV3}
      />
    );
  } else if (primaryType === "ConfirmationCard") {
    const phase = (primary?.props?.phase as "PENDING" | "CONFIRMED" | undefined) ?? "PENDING";
    const preview = primary?.props?.preview as Record<string, unknown> | undefined;
    const pending = primary?.props?.pending as
      | { actionId: string; actionType: string }
      | undefined;
    const result = primary?.props?.result as Record<string, unknown> | undefined;

    body = (
      <InlineConfirmationCardV3
        phase={phase}
        preview={preview ?? null}
        pending={pending ?? null}
        result={result ?? null}
        isAgentLoading={isAgentLoading}
        onResumeV3={onResumeV3}
      />
    );
  } else if (primaryType === "OrderListPicker") {
    // RETURNS' order list (returnEligibleOrders) and ORDER_STATUS's
    // (orders) are separate canvasData keys — whichever one this turn
    // actually populated is the one to show.
    const orderList = orders.length > 0 ? orders : mapEligibleOrdersToScenarios(returnEligibleOrders);

    body = (
      <InlineOrderList
        orders={orderList}
        isAgentLoading={isAgentLoading}
        loadingOrderNumber={loadingOrderNumber}
        onSelectOrder={onSelectOrder}
      />
    );
  } else if (primaryType === "OrderSummaryCard" && selectedOrder) {
    body = (
      <InlineOrderSummaryCardV3 order={selectedOrder} supplementalTypes={supplementalTypes} />
    );
  } else {
    body = <InlineWelcome />;
  }

  // SuggestedActions is allowed in every capability's catalog (agent/v3/
  // capabilities/*.py) but no capability's prompt or deterministic
  // fallback actually populates its props with real chip labels yet — so
  // there's nothing to render here today. When the backend starts
  // proposing real content, this is where it plugs in (a chip's click
  // should behave like typing that label, which needs a V3 sendFreeText
  // equivalent threaded down from AssistantProvider).

  return body;
}

function mapEligibleOrdersToScenarios(
  eligibleOrders: CancellationEligibleOrder[]
): OrderScenario[] {
  return eligibleOrders.map((order) => ({
    orderNumber: order.orderNumber,
    status: order.orderStatus,
    promise: "",
    date: order.orderDate,
    items: `${order.items.length} item${order.items.length === 1 ? "" : "s"}`,
    customerName: "",
    orderPromiseSummary: "",
    promiseStatusLabel: order.orderStatus,
    promiseStatusTone: "neutral",
    customerSummary: "",
    packages: [],
  }));
}
