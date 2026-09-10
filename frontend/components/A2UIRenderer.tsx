// frontend/components/A2UIRenderer.tsx

import { InlineCancellationBuilder } from "@/components/assistant/inline/InlineCancellationBuilder";
import { InlineCancellationConfirmation } from "@/components/assistant/inline/InlineCancellationConfirmation";
import { InlineCancellationItemPicker } from "@/components/assistant/inline/InlineCancellationItemPicker";
import { InlineCancellationOrderPicker } from "@/components/assistant/inline/InlineCancellationOrderPicker";
import { InlineClaimConfirmation } from "@/components/assistant/inline/InlineClaimConfirmation";
import { InlineClaimForm } from "@/components/assistant/inline/InlineClaimForm";
import { InlineConfirmationCard } from "@/components/assistant/inline/InlineConfirmationCard";
import { InlineDecomposedReturnItem } from "@/components/assistant/inline/InlineDecomposedReturnItem";
import { InlineOrderList } from "@/components/assistant/inline/InlineOrderList";
import { InlineOrderStatus } from "@/components/assistant/inline/InlineOrderStatus";
import { InlineReturnMethodPrompt } from "@/components/assistant/inline/InlineReturnMethodPrompt";
import { InlineReturnReasonPrompt } from "@/components/assistant/inline/InlineReturnReasonPrompt";
import { InlineWelcome } from "@/components/assistant/inline/InlineWelcome";
import type { A2UIComponent, AgentUIMode } from "@/lib/agent-api";
import type {
  A2UIComponentV2,
  ConfirmationResume,
  StructuredSelectionResume,
  V2ComponentType,
} from "@/lib/agent-api-v2";
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
  uiMode: AgentUIMode | V2ComponentType;
  components: (A2UIComponent | A2UIComponentV2)[];
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
  // V2-only — order selection itself reuses onSelectOrder (routed
  // per-turn by AssistantTranscript); this is for every other structured
  // interaction a V2 turn can originate: item/reason/method selection and
  // Confirm/Decline clicks on a pending sensitive action.
  returnEligibility?: Record<string, unknown> | null;
  returnReasonOptions?: string[];
  orderNumber?: string | null;
  onResumeV2?: (
    resume: StructuredSelectionResume | ConfirmationResume,
    userFacingLabel: string
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
  // V2-only — additive; none of these rename or replace a V1 entry above,
  // per plan section 8's naming note.
  "orderStatus",
  "cancellationConfirmationPending",
  "returnConfirmationPending",
  "returnSubmitted",
  "claimConfirmationPending",
  "returnItemSelection",
  // 2026-08 structured-interaction fix — CANCELLATION/RETURNS' remaining
  // interactive stages.
  "cancellationOrderSelection",
  "cancellationItemSelection",
  "returnReasonPrompt",
  "returnMethodPrompt",
] as const;

type PrimaryComponentType = (typeof PRIMARY_COMPONENT_TYPES)[number];

function isPrimaryComponentType(type: string): type is PrimaryComponentType {
  return PRIMARY_COMPONENT_TYPES.includes(type as PrimaryComponentType);
}

function resolvePrimaryComponent(
  components: (A2UIComponent | A2UIComponentV2)[],
  fallbackMode: AgentUIMode | V2ComponentType
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
  returnEligibility,
  returnReasonOptions,
  orderNumber,
  onResumeV2,
}: A2UIRendererProps) {
  const primaryComponentType = resolvePrimaryComponent(components, uiMode);

  if (primaryComponentType === "cancellationOrderSelection") {
    return (
      <InlineCancellationOrderPicker
        eligibleOrders={eligibleOrders}
        isAgentLoading={isAgentLoading}
        onResumeV2={onResumeV2 ?? (() => {})}
      />
    );
  }

  if (primaryComponentType === "cancellationItemSelection") {
    return (
      <InlineCancellationItemPicker
        eligibleOrders={eligibleOrders}
        orderNumber={orderNumber}
        isAgentLoading={isAgentLoading}
        onResumeV2={onResumeV2 ?? (() => {})}
      />
    );
  }

  if (primaryComponentType === "returnReasonPrompt") {
    return (
      <InlineReturnReasonPrompt
        reasonOptions={returnReasonOptions ?? []}
        isAgentLoading={isAgentLoading}
        onResumeV2={onResumeV2 ?? (() => {})}
      />
    );
  }

  if (primaryComponentType === "returnMethodPrompt") {
    return (
      <InlineReturnMethodPrompt
        returnEligibility={returnEligibility as { returnMethods?: string[] } | null}
        isAgentLoading={isAgentLoading}
        onResumeV2={onResumeV2 ?? (() => {})}
      />
    );
  }

  if (primaryComponentType === "orderStatus" && selectedOrder) {
    return (
      <InlineOrderStatus
        order={selectedOrder}
        onReportWrongDelivery={onReportWrongDelivery}
      />
    );
  }

  if (
    primaryComponentType === "cancellationConfirmationPending" ||
    primaryComponentType === "returnConfirmationPending" ||
    primaryComponentType === "claimConfirmationPending"
  ) {
    const primary = components.find(
      (component) => component.type === primaryComponentType
    );
    const props = (primary?.props ?? {}) as {
      preview?: Record<string, unknown>;
      pending?: { actionId: string; actionType: string };
    };

    return (
      <InlineConfirmationCard
        phase="PENDING"
        preview={props.preview ?? null}
        pending={props.pending ?? null}
        isAgentLoading={isAgentLoading}
        onResumeV2={onResumeV2}
      />
    );
  }

  if (primaryComponentType === "returnSubmitted") {
    const primary = components.find(
      (component) => component.type === "returnSubmitted"
    );
    const props = (primary?.props ?? {}) as { result?: Record<string, unknown> };

    return (
      <InlineConfirmationCard
        phase="CONFIRMED"
        result={props.result ?? null}
        isAgentLoading={isAgentLoading}
      />
    );
  }

  if (primaryComponentType === "returnItemSelection") {
    return (
      <InlineDecomposedReturnItem
        returnEligibility={returnEligibility}
        isAgentLoading={isAgentLoading}
        onResumeV2={onResumeV2 ?? (() => {})}
      />
    );
  }

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
