// frontend/components/PromiseDashboardCanvas.tsx
//
// Not used by the assistant panel (see components/assistant/inline/InlineOrderStatus.tsx)
// — retained for the future full-page /orders/[orderNumber] route (Phase 3).

import type { ReactNode } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Camera,
  CheckCircle2,
  Clock3,
  CloudRain,
  Gift,
} from "lucide-react";
import type {
  OrderScenario,
  PackageLine,
  PromiseTone,
  ServiceRecovery,
  ShipmentPackage,
} from "@/types/order";

export function PromiseDashboardCanvas({
  order,
  onBackToOrders,
  onReportWrongDelivery,
}: {
  order: OrderScenario;
  onBackToOrders: () => void;
  onReportWrongDelivery: (order: OrderScenario) => void;
}) {
  return (
    <div className="min-h-full rounded-[1.5rem] bg-white p-8">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <button
            onClick={onBackToOrders}
            className="mb-5 inline-flex items-center gap-2 rounded-full border border-black/10 bg-[#fbfaf7] px-4 py-2 text-sm font-bold text-neutral-700 transition hover:border-black/30"
          >
            <ArrowLeft size={16} />
            Back to orders
          </button>

          <p className="mb-3 text-xs font-black uppercase tracking-[0.28em] text-neutral-400">
            Promise Sense Dashboard
          </p>
          <h2 className="text-4xl font-black tracking-[-0.055em] text-neutral-950">
            Order {order.orderNumber}
          </h2>
          <p className="mt-2 text-sm font-semibold text-neutral-500">
            Placed {order.date} · {order.packages.length} package
            {order.packages.length > 1 ? "s" : ""} · {order.orderPromiseSummary}
          </p>
        </div>

        <PromiseStatusBadge tone={order.promiseStatusTone}>
          {order.promiseStatusLabel}
        </PromiseStatusBadge>
      </div>

      <section className="mb-5 rounded-[2rem] border border-black/10 bg-[#fbfaf7] p-6">
        <p className="text-lg font-bold leading-8 text-neutral-900">
          {order.customerSummary}
        </p>
      </section>

      <div className="space-y-5">
        {order.packages.map((pkg) => (
          <PackagePromiseCard key={pkg.trackingNumber} pkg={pkg} />
        ))}

        {order.serviceRecovery && (
          <ServiceRecoveryStrip recovery={order.serviceRecovery} />
        )}

        <DeliveryProofSection
          order={order}
          onReportWrongDelivery={onReportWrongDelivery}
        />
      </div>
    </div>
  );
}

function PromiseStatusBadge({
  tone,
  children,
}: {
  tone: PromiseTone;
  children: ReactNode;
}) {
  const styles = {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    danger: "border-rose-200 bg-rose-50 text-rose-800",
    neutral: "border-neutral-200 bg-neutral-100 text-neutral-600",
  };

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-black ${styles[tone]}`}
    >
      {tone === "success" && <CheckCircle2 size={16} />}
      {tone === "warning" && <CloudRain size={16} />}
      {tone === "danger" && <AlertTriangle size={16} />}
      {children}
    </div>
  );
}

function PackagePromiseCard({ pkg }: { pkg: ShipmentPackage }) {
  return (
    <section className="rounded-[2rem] border border-black/10 bg-[#f6f4f0] p-5">
      <div className="mb-4 grid gap-3 lg:grid-cols-4">
        <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/10">
          <p className="text-xs font-black uppercase tracking-[0.2em] text-neutral-400">
            Package #{pkg.packageNumber}
          </p>
          <h3 className="mt-2 text-xl font-black tracking-[-0.04em]">
            {pkg.status}
          </h3>
        </div>

        <CompactMeta label="Tracking" value={pkg.trackingNumber} />
        <CompactMeta label="Carrier" value={pkg.carrier} />
        <CompactMeta
          label="Promised delivery"
          value={pkg.promisedDeliveryResult}
          tone={
            pkg.promisedDeliveryResult === "Met"
              ? "success"
              : pkg.promisedDeliveryResult === "At risk"
                ? "warning"
                : "danger"
          }
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.75fr_1.25fr]">
        <PackageItems items={pkg.items} />
        <PromiseMeter pkg={pkg} />
      </div>
    </section>
  );
}

function CompactMeta({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: PromiseTone;
}) {
  const toneStyles = {
    success: "text-emerald-700",
    warning: "text-amber-700",
    danger: "text-rose-700",
    neutral: "text-neutral-600",
  };

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/10">
      <p className="text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
        {label}
      </p>
      <p
        className={`mt-2 break-words text-base font-black tracking-[-0.03em] ${
          tone ? toneStyles[tone] : "text-neutral-950"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function PackageItems({ items }: { items: PackageLine[] }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/10">
      <p className="mb-3 text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
        Package contains
      </p>
      <div className="space-y-3">
        {items.map((line) => (
          <div
            key={`${line.itemName}-${line.color}-${line.size}`}
            className="flex gap-4 rounded-2xl border border-black/10 bg-[#fbfaf7] p-3"
          >
            <div
              className={`h-18 w-18 min-h-[72px] min-w-[72px] rounded-2xl bg-gradient-to-br ${line.imageGradient}`}
            />
            <div className="min-w-0 flex-1">
              <p className="font-black tracking-[-0.03em]">{line.itemName}</p>
              <p className="mt-1 text-sm text-neutral-500">
                {line.color} • Size {line.size} • Qty {line.qty}
              </p>
              <p className="mt-2 text-sm font-bold">{line.price}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PromiseMeter({ pkg }: { pkg: ShipmentPackage }) {
  const sortedMilestones = [...pkg.milestones].sort(
    (a, b) => a.position - b.position
  );

  const visibleMilestones = sortedMilestones.filter(
    (milestone) => milestone.tone !== "promise"
  );

  const promiseMarker = sortedMilestones.find(
    (milestone) => milestone.tone === "promise"
  );

  const lastVisibleMilestone =
    visibleMilestones[visibleMilestones.length - 1] ?? sortedMilestones[0];

  const warningMilestone = sortedMilestones.find(
    (milestone) => milestone.tone === "warning"
  );

  const hasWarning = sortedMilestones.some(
    (milestone) => milestone.tone === "warning"
  );

  const hasDanger = sortedMilestones.some(
    (milestone) => milestone.tone === "danger"
  );

  const barEnd = lastVisibleMilestone?.position ?? 70;
  const promisePosition = promiseMarker?.position ?? 80;
  const warningPosition = warningMilestone?.position ?? 0;

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-black/10">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-black p-3 text-white">
            <Clock3 size={18} />
          </div>
          <div>
            <h4 className="text-lg font-black tracking-[-0.03em]">
              Promise timeline
            </h4>
            <p className="text-sm text-neutral-500">
              Package progress compared to original promise
            </p>
          </div>
        </div>

        <a
          href={pkg.fullTrackingUrl}
          className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-[#fbfaf7] px-4 py-2 text-sm font-black text-neutral-800 transition hover:border-black/30"
        >
          View full tracking details
          <ArrowRight size={15} />
        </a>
      </div>

      <div className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-5">
        <div className="relative h-28">
          <div className="absolute left-0 right-0 top-11 h-4 rounded-full bg-neutral-200" />

          {!hasWarning && !hasDanger && (
            <div
              className="absolute left-0 top-11 h-4 rounded-full bg-emerald-500"
              style={{ width: `${barEnd}%` }}
            />
          )}

          {hasWarning && hasDanger && (
            <>
              <div
                className="absolute left-0 top-11 h-4 rounded-l-full bg-emerald-500"
                style={{ width: `${warningPosition}%` }}
              />
              <div
                className="absolute top-11 h-4 bg-amber-400"
                style={{
                  left: `${warningPosition}%`,
                  width: `${Math.max(promisePosition - warningPosition, 0)}%`,
                }}
              />
              <div
                className="absolute top-11 h-4 rounded-r-full bg-rose-500"
                style={{
                  left: `${promisePosition}%`,
                  width: `${Math.max(barEnd - promisePosition, 0)}%`,
                }}
              />
            </>
          )}

          {!hasWarning && hasDanger && (
            <>
              <div
                className="absolute left-0 top-11 h-4 rounded-l-full bg-emerald-500"
                style={{ width: `${Math.min(promisePosition, barEnd)}%` }}
              />
              <div
                className="absolute top-11 h-4 rounded-r-full bg-rose-500"
                style={{
                  left: `${promisePosition}%`,
                  width: `${Math.max(barEnd - promisePosition, 0)}%`,
                }}
              />
            </>
          )}

          {hasWarning && !hasDanger && (
            <>
              <div
                className="absolute left-0 top-11 h-4 rounded-l-full bg-emerald-500"
                style={{ width: `${warningPosition}%` }}
              />
              <div
                className="absolute top-11 h-4 rounded-r-full bg-amber-400"
                style={{
                  left: `${warningPosition}%`,
                  width: `${Math.max(barEnd - warningPosition, 0)}%`,
                }}
              />
            </>
          )}

          {promiseMarker && (
            <div
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center"
              style={{ left: `${promiseMarker.position}%` }}
            >
              <div className="mb-1 rounded-full bg-black px-3 py-1 text-[10px] font-black uppercase tracking-wider text-white">
                Promise
              </div>
              <div className="h-[78px] w-px bg-black" />
            </div>
          )}

          {visibleMilestones.map((milestone) => (
            <div
              key={`${pkg.trackingNumber}-${milestone.label}`}
              className="absolute top-[34px] flex -translate-x-1/2 flex-col items-center"
              style={{ left: `${milestone.position}%` }}
            >
              <div
                className={`flex h-9 w-9 items-center justify-center rounded-full border-2 border-white shadow-sm ${
                  milestone.tone === "success"
                    ? "bg-emerald-500 text-white"
                    : milestone.tone === "warning"
                      ? "bg-amber-400 text-black"
                      : milestone.tone === "danger"
                        ? "bg-rose-500 text-white"
                        : "bg-neutral-500 text-white"
                }`}
              >
                {milestone.tone === "warning" || milestone.tone === "danger" ? (
                  <AlertTriangle size={15} />
                ) : (
                  <CheckCircle2 size={15} />
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="grid gap-2 md:grid-cols-4">
          {sortedMilestones.map((milestone) => (
            <div
              key={`${pkg.trackingNumber}-${milestone.label}-${milestone.date}`}
              className={`rounded-2xl p-3 ${
                milestone.tone === "promise"
                  ? "border border-black/10 bg-white"
                  : "bg-white"
              }`}
            >
              <p className="text-sm font-black tracking-[-0.03em]">
                {milestone.tone === "promise"
                  ? "Original promise"
                  : milestone.label}
              </p>
              <p className="mt-1 text-xs font-medium leading-4 text-neutral-500">
                {milestone.date}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ServiceRecoveryStrip({ recovery }: { recovery: ServiceRecovery }) {
  const isRefund = recovery.tone === "refund";

  const cardStyle = isRefund
    ? "border-rose-200 bg-rose-50 text-rose-950"
    : "border-amber-200 bg-amber-50 text-amber-950";

  const iconStyle = isRefund
    ? "bg-rose-100 text-rose-700"
    : "bg-amber-100 text-amber-700";

  return (
    <section className={`rounded-[2rem] border p-6 ${cardStyle}`}>
      <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div className="flex gap-4">
          <div className={`h-fit rounded-2xl p-3 ${iconStyle}`}>
            <Gift size={22} />
          </div>
          <div>
            <h3 className="text-2xl font-black tracking-[-0.05em]">
              {recovery.title}
            </h3>
            <p className="mt-2 max-w-3xl text-sm leading-7 opacity-80">
              {recovery.description}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap gap-2">
          <span className="rounded-full bg-white px-4 py-2 text-sm font-black text-neutral-950 shadow-sm ring-1 ring-black/10">
            {recovery.badge}
          </span>
          {recovery.secondaryBadge && (
            <span className="rounded-full bg-white px-4 py-2 text-sm font-black text-neutral-950 shadow-sm ring-1 ring-black/10">
              {recovery.secondaryBadge}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

function DeliveryProofSection({
  order,
  onReportWrongDelivery,
}: {
  order: OrderScenario;
  onReportWrongDelivery: (order: OrderScenario) => void;
}) {
  const packagesWithProof = order.packages.filter((pkg) => pkg.deliveryProof);

  if (packagesWithProof.length === 0) {
    return null;
  }

  return (
    <section className="mb-12 rounded-[2rem] border border-black/10 bg-white p-6">
      <div className="mb-5 flex items-center gap-3">
        <div className="rounded-2xl bg-black p-3 text-white">
          <Camera size={20} />
        </div>
        <div>
          <h3 className="text-xl font-black tracking-[-0.04em]">
            Delivery proof
          </h3>
          <p className="text-sm text-neutral-500">
            Proof photo cards appear when carrier proof data is available.
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {packagesWithProof.map((pkg) => (
          <div
            key={`${pkg.trackingNumber}-proof`}
            className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-4"
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="font-black tracking-[-0.03em]">
                  Package #{pkg.packageNumber}
                </p>
                <p className="text-sm text-neutral-500">
                  {pkg.deliveryProof?.deliveredAt}
                </p>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-black ring-1 ring-black/10">
                {pkg.deliveryProof?.locationNote}
              </span>
            </div>

            <div className="flex h-40 items-center justify-center rounded-3xl bg-gradient-to-br from-stone-200 via-stone-100 to-neutral-300 text-center">
              <div>
                <Camera className="mx-auto mb-3 text-neutral-500" size={28} />
                <p className="text-sm font-black text-neutral-700">
                  Proof photo placeholder
                </p>
                <p className="mt-1 text-xs text-neutral-500">
                  {pkg.deliveryProof?.imageDescription}
                </p>
              </div>
            </div>

            <button
              onClick={() => onReportWrongDelivery(order)}
              className="mt-4 w-full rounded-2xl border border-black/10 bg-white px-4 py-3 text-sm font-black transition hover:border-black/30"
            >
              Report delivery issue
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}