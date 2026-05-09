// frontend/components/A2UIRenderer.tsx

import { AgentProgressPanel } from "@/components/AgentProgressPanel";
import { ClaimSubmittedCanvas } from "@/components/ClaimSubmittedCanvas";
import { OrderSelectionCanvas } from "@/components/OrderSelectionCanvas";
import { PromiseDashboardCanvas } from "@/components/PromiseDashboardCanvas";
import { WelcomeCanvas } from "@/components/WelcomeCanvas";
import { WrongDeliveryClaimCanvas } from "@/components/WrongDeliveryClaimCanvas";
import type { A2UIComponent, AgentStep, AgentUIMode } from "@/lib/agent-api";
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
  agentProgressSteps: AgentStep[];
  claimResult: ClaimSubmissionResult | null;
  onSelectOrder: (order: OrderScenario) => void;
  onReportWrongDelivery: (order: OrderScenario) => void;
  onSubmitWrongDeliveryClaim: (claim: WrongDeliveryClaimDraft) => void;
  onBackToOrders: () => void;
  onBackToDashboard: () => void;
};

const PRIMARY_COMPONENT_TYPES = [
  "welcome",
  "orderSelection",
  "promiseDashboard",
  "wrongDeliveryClaim",
  "claimSubmitted",
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
  agentProgressSteps,
  claimResult,
  onSelectOrder,
  onReportWrongDelivery,
  onSubmitWrongDeliveryClaim,
  onBackToOrders,
  onBackToDashboard,
}: A2UIRendererProps) {
  if (isAgentLoading && agentProgressSteps.length > 0) {
    return <AgentProgressPanel steps={agentProgressSteps} />;
  }

  const primaryComponentType = resolvePrimaryComponent(components, uiMode);

  if (primaryComponentType === "orderSelection") {
    return (
      <OrderSelectionCanvas
        orders={orders}
        isAgentLoading={isAgentLoading}
        loadingOrderNumber={loadingOrderNumber}
        onSelectOrder={onSelectOrder}
      />
    );
  }

  if (primaryComponentType === "promiseDashboard" && selectedOrder) {
    return (
      <PromiseDashboardCanvas
        order={selectedOrder}
        onBackToOrders={onBackToOrders}
        onReportWrongDelivery={onReportWrongDelivery}
      />
    );
  }

  if (primaryComponentType === "wrongDeliveryClaim") {
    return (
      <WrongDeliveryClaimCanvas
        order={selectedOrder}
        onBackToDashboard={onBackToDashboard}
        onSubmitClaim={onSubmitWrongDeliveryClaim}
      />
    );
  }

  if (primaryComponentType === "claimSubmitted") {
    return (
      <ClaimSubmittedCanvas
        claimResult={claimResult}
        onBackToOrders={onBackToOrders}
      />
    );
  }

  return <WelcomeCanvas />;
}