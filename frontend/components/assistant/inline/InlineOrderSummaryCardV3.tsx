// frontend/components/assistant/inline/InlineOrderSummaryCardV3.tsx
//
// V3-only. Renders V3's OrderSummaryCard a2ui type (the ORDER_STATUS
// primary) plus its supplemental facets — StatusPill, TrackingTimeline,
// DeliveryProofCard, ServiceRecoveryBanner — as sections within one card,
// each shown only when the turn's a2ui[] actually proposed that
// supplemental type (agent/v3/ui/catalog.py's PRIMARY_COMPONENT_TYPES vs.
// supplemental split: OrderSummaryCard anchors the screen, the rest render
// "alongside" it — implemented here as sections of one card rather than
// separate floating cards, since a tracking timeline reads naturally as
// part of an order's summary, not a sibling of it).
//
// Adapted from InlineOrderStatus (V1) — same underlying OrderScenario data
// (agent/v3/tools/order_tools.py reuses tools.get_order_promise_dashboard
// directly, so the shape is byte-identical), but drops the "Report
// delivery issue" button: WRONG_DELIVERY doesn't exist as a V3 capability
// yet, so that action has nowhere to go.

import { AlertTriangle, CheckCircle2, Circle, CloudRain } from "lucide-react";
import type { ReactNode } from "react";
import { InlineDeliveryTimeline } from "@/components/assistant/inline/InlineDeliveryTimeline";
import { InlineServiceRecovery } from "@/components/assistant/inline/InlineServiceRecovery";
import type { OrderScenario, PromiseTone, ShipmentPackage } from "@/types/order";
import type { V3ComponentType } from "@/lib/agent-api-v3";

const statusIcon: Record<PromiseTone, ReactNode> = {
  success: <CheckCircle2 size={13} />,
  warning: <CloudRain size={13} />,
  danger: <AlertTriangle size={13} />,
  neutral: <CheckCircle2 size={13} />,
};

const statusBadgeClass: Record<PromiseTone, string> = {
  success: "bg-emerald-50 text-emerald-800",
  warning: "bg-amber-50 text-amber-800",
  danger: "bg-rose-50 text-rose-800",
  neutral: "bg-neutral-100 text-neutral-600",
};

function packageTone(pkg: ShipmentPackage): PromiseTone {
  if (pkg.promisedDeliveryResult === "Met") return "success";
  if (pkg.promisedDeliveryResult === "At risk") return "warning";
  return "danger";
}

function PackageSummarySection({
  pkg,
  showTimeline,
  showDeliveryProof,
}: {
  pkg: ShipmentPackage;
  showTimeline: boolean;
  showDeliveryProof: boolean;
}) {
  const tone = packageTone(pkg);

  return (
    <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-bold text-neutral-500">
          Package {pkg.packageNumber} · {pkg.carrier}
        </p>
        {/* StatusPill */}
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-black ${statusBadgeClass[tone]}`}
        >
          {statusIcon[tone]}
          {pkg.promisedDeliveryResult}
        </span>
      </div>

      <p className="mt-1.5 truncate text-xs text-neutral-500" title={pkg.trackingNumber}>
        Tracking: <span className="text-neutral-700">{pkg.trackingNumber}</span>
      </p>

      {showTimeline && (
        <div className="mt-3">
          <InlineDeliveryTimeline milestones={pkg.milestones} />
        </div>
      )}

      {showDeliveryProof && pkg.deliveryProof && (
        <div className="mt-3 rounded-xl border border-black/10 bg-white p-2.5">
          <div className="flex items-center gap-1.5 text-xs font-black text-neutral-800">
            <Circle size={8} fill="currentColor" className="text-emerald-500" />
            Delivered {pkg.deliveryProof.deliveredAt}
          </div>
          <p className="mt-1 text-xs text-neutral-500">{pkg.deliveryProof.locationNote}</p>
        </div>
      )}

      <div className="mt-3">
        <a
          href={pkg.fullTrackingUrl}
          className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-black text-neutral-800 transition hover:border-black/30"
        >
          Track package
        </a>
      </div>
    </div>
  );
}

export function InlineOrderSummaryCardV3({
  order,
  supplementalTypes,
}: {
  order: OrderScenario;
  supplementalTypes: V3ComponentType[];
}) {
  // Default to showing every facet when the agent didn't explicitly curate
  // a subset (e.g. the deterministic fallback, which only ever proposes
  // OrderSummaryCard alone) — an order summary with no timeline or status
  // at all would be a strictly worse default than showing everything.
  const hasSupplementalProposal = supplementalTypes.length > 0;
  const showTimeline = !hasSupplementalProposal || supplementalTypes.includes("TrackingTimeline");
  const showDeliveryProof =
    !hasSupplementalProposal || supplementalTypes.includes("DeliveryProofCard");
  const showServiceRecovery =
    !hasSupplementalProposal || supplementalTypes.includes("ServiceRecoveryBanner");

  return (
    <div className="space-y-2">
      {order.packages.map((pkg) => (
        <PackageSummarySection
          key={pkg.trackingNumber}
          pkg={pkg}
          showTimeline={showTimeline}
          showDeliveryProof={showDeliveryProof}
        />
      ))}

      {showServiceRecovery && order.serviceRecovery && (
        <InlineServiceRecovery recovery={order.serviceRecovery} />
      )}
    </div>
  );
}
