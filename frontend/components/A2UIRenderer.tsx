// frontend/components/A2UIRenderer.tsx

import { InlineCancellationBuilder } from "@/components/assistant/inline/InlineCancellationBuilder";
import { InlineCancellationConfirmation } from "@/components/assistant/inline/InlineCancellationConfirmation";
import { InlineClaimConfirmation } from "@/components/assistant/inline/InlineClaimConfirmation";
import { InlineClaimForm } from "@/components/assistant/inline/InlineClaimForm";
import { InlineOrderList } from "@/components/assistant/inline/InlineOrderList";
import { InlineOrderStatus } from "@/components/assistant/inline/InlineOrderStatus";
import { InlineWelcome } from "@/components/assistant/inline/InlineWelcome";
import type { A2UIComponent, AgentUIMode } from "@/lib/agent-api";
import type {
  CancellationEligibleOrder,
  CancellationLineSelection,
  CancellationResult,
} from "@/types/cancellation";
import type {
  ClaimSubmissionResult,
  OrderScenario,
  WrongDeliveryClaimDraft,
} from "@/types/order";

type A2UIRendererProps = {
  uiMode: AgentUIMode;
  components: A2UIComponent[];
  selectedOrder: OrderScenario | null;
  orders: OrderScenario[];
  isAgentLoading: boolean;
  loadingOrderNumber: string | null;
  claimResult: ClaimSubmissionResult | null;
  eligibleOrders: CancellationEligibleOrder[];
  cancellationResult: CancellationResult | null;
  onSelectOrder: (order: OrderScenario) => void;
  onReportWrongDelivery: (order: OrderScenario) => void;
  onSubmitWrongDeliveryClaim: (claim: WrongDeliveryClaimDraft) => void;
  onSubmitOrderCancellation: (
    orderNumber: string,
    lineSelections: CancellationLineSelection[],
    reason: string
  ) => void;
};

const PRIMARY_COMPONENT_TYPES = [
  "welcome",
  "orderSelection",
  "promiseDashboard",
  "wrongDeliveryClaim",
  "claimSubmitted",
  "cancellationBuilder",
  "cancellationConfirmed",
] as const;

type PrimaryComponentType = (typeof PRIMARY_COMPONENT_TYPES)[number];

function isPrimaryComponentType(type: string): type is PrimaryComponentType {
  return PRIMARY_COMPONENT_TYPES.includes(type as PrimaryComponentType);
}

function resolvePrimaryComponent(
  components: A2UIComponent[],
  fallbackMode: AgentUIMode
): PrimaryComponentType {
  const primaryComponent = components.find((component) =>
    isPrimaryComponentType(component.type)
  );

  if (primaryComponent && isPrimaryComponentType(primaryComponent.type)) {
    return primaryComponent.type;
  }

  if (isPrimaryComponentType(fallbackMode)) {
    return fallbackMode;
  }

  return "welcome";
}

export function A2UIRenderer({
  uiMode,
  components,
  selectedOrder,
  orders,
  isAgentLoading,
  loadingOrderNumber,
  claimResult,
  eligibleOrders,
  cancellationResult,
  onSelectOrder,
  onReportWrongDelivery,
  onSubmitWrongDeliveryClaim,
  onSubmitOrderCancellation,
}: A2UIRendererProps) {
  const primaryComponentType = resolvePrimaryComponent(components, uiMode);

  if (primaryComponentType === "orderSelection") {
    return (
      <InlineOrderList
        orders={orders}
        isAgentLoading={isAgentLoading}
        loadingOrderNumber={loadingOrderNumber}
        onSelectOrder={onSelectOrder}
      />
    );
  }

  if (primaryComponentType === "promiseDashboard" && selectedOrder) {
    return (
      <InlineOrderStatus
        order={selectedOrder}
        onReportWrongDelivery={onReportWrongDelivery}
      />
    );
  }

  if (primaryComponentType === "wrongDeliveryClaim") {
    return (
      <InlineClaimForm
        order={selectedOrder}
        onSubmitClaim={onSubmitWrongDeliveryClaim}
      />
    );
  }

  if (primaryComponentType === "claimSubmitted") {
    return <InlineClaimConfirmation claimResult={claimResult} />;
  }

  if (primaryComponentType === "cancellationBuilder") {
    return (
      <InlineCancellationBuilder
        eligibleOrders={eligibleOrders}
        onSubmit={onSubmitOrderCancellation}
      />
    );
  }

  if (primaryComponentType === "cancellationConfirmed") {
    return (
      <InlineCancellationConfirmation cancellationResult={cancellationResult} />
    );
  }

  return <InlineWelcome />;
}
