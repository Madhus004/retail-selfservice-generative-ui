// frontend/components/assistant/inline/InlineOrderStatus.tsx
//
// Panel-native replacement for PromiseDashboardCanvas. Renders one compact
// status card per package (not a 4-column meta grid) plus a compact
// service-recovery card when applicable — no "back to orders" action, since
// the order-selection turn is already visible just above in the transcript.

import { AlertTriangle, CheckCircle2, CloudRain } from "lucide-react";
import type { ReactNode } from "react";
import { InlineDeliveryTimeline } from "@/components/assistant/inline/InlineDeliveryTimeline";
import { InlineServiceRecovery } from "@/components/assistant/inline/InlineServiceRecovery";
import type { OrderScenario, PromiseTone, ShipmentPackage } from "@/types/order";

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

function PackageStatusCard({
  pkg,
  onReportWrongDelivery,
}: {
  pkg: ShipmentPackage;
  onReportWrongDelivery: () => void;
}) {
  const tone = packageTone(pkg);

  return (
    <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-bold text-neutral-500">
          Package {pkg.packageNumber} · {pkg.carrier}
        </p>
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-black ${statusBadgeClass[tone]}`}
        >
          {statusIcon[tone]}
          {pkg.promisedDeliveryResult}
        </span>
      </div>

      <p
        className="mt-1.5 truncate text-xs text-neutral-500"
        title={pkg.trackingNumber}
      >
        Tracking: <span className="text-neutral-700">{pkg.trackingNumber}</span>
      </p>

      <div className="mt-3">
        <InlineDeliveryTimeline milestones={pkg.milestones} />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <a
          href={pkg.fullTrackingUrl}
          className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-black text-neutral-800 transition hover:border-black/30"
        >
          Track package
        </a>

        {pkg.deliveryProof && (
          <button
            onClick={onReportWrongDelivery}
            className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-black text-neutral-800 transition hover:border-black/30"
          >
            Report delivery issue
          </button>
        )}
      </div>
    </div>
  );
}

export function InlineOrderStatus({
  order,
  onReportWrongDelivery,
}: {
  order: OrderScenario;
  onReportWrongDelivery: (order: OrderScenario) => void;
}) {
  return (
    <div className="space-y-2">
      {order.packages.map((pkg) => (
        <PackageStatusCard
          key={pkg.trackingNumber}
          pkg={pkg}
          onReportWrongDelivery={() => onReportWrongDelivery(order)}
        />
      ))}

      {order.serviceRecovery && (
        <InlineServiceRecovery recovery={order.serviceRecovery} />
      )}
    </div>
  );
}
