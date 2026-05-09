// frontend/components/SupportWorkspace.tsx

import { A2UIRenderer } from "@/components/A2UIRenderer";
import { ChatPanel } from "@/components/ChatPanel";
import type { A2UIComponent, AgentStep, AgentUIMode } from "@/lib/agent-api";
import type {
  ClaimSubmissionResult,
  OrderScenario,
  WrongDeliveryClaimDraft,
} from "@/types/order";

export function SupportWorkspace({
  canvasMode,
  a2uiComponents,
  selectedOrder,
  orders,
  isAgentLoading,
  loadingOrderNumber,
  agentProgressSteps,
  claimResult,
  onWhereIsMyOrder,
  onSelectOrder,
  onReportWrongDelivery,
  onSubmitWrongDeliveryClaim,
  onBackToOrders,
  onBackToDashboard,
}: {
  canvasMode: AgentUIMode;
  a2uiComponents: A2UIComponent[];
  selectedOrder: OrderScenario | null;
  orders: OrderScenario[];
  isAgentLoading: boolean;
  loadingOrderNumber: string | null;
  agentProgressSteps: AgentStep[];
  claimResult: ClaimSubmissionResult | null;
  onWhereIsMyOrder: () => void;
  onSelectOrder: (order: OrderScenario) => void;
  onReportWrongDelivery: (order: OrderScenario) => void;
  onSubmitWrongDeliveryClaim: (claim: WrongDeliveryClaimDraft) => void;
  onBackToOrders: () => void;
  onBackToDashboard: () => void;
}) {
  return (
    <section className="h-[calc(100vh-190px)] min-h-[640px] max-h-[820px] overflow-hidden rounded-[2rem] border border-black/10 bg-white shadow-2xl shadow-black/10">
      <div className="grid h-full grid-cols-1 lg:grid-cols-[30%_70%]">
        <ChatPanel
          isAgentLoading={isAgentLoading}
          agentProgressSteps={agentProgressSteps}
          onWhereIsMyOrder={onWhereIsMyOrder}
        />

        <div className="h-full overflow-y-auto bg-[#fbfaf7] p-6 pb-32">
          <A2UIRenderer
            uiMode={canvasMode}
            components={a2uiComponents}
            selectedOrder={selectedOrder}
            orders={orders}
            isAgentLoading={isAgentLoading}
            loadingOrderNumber={loadingOrderNumber}
            agentProgressSteps={agentProgressSteps}
            claimResult={claimResult}
            onSelectOrder={onSelectOrder}
            onReportWrongDelivery={onReportWrongDelivery}
            onSubmitWrongDeliveryClaim={onSubmitWrongDeliveryClaim}
            onBackToOrders={onBackToOrders}
            onBackToDashboard={onBackToDashboard}
          />
        </div>
      </div>
    </section>
  );
}