// frontend/components/assistant/inline/InlineDeliveryTimeline.tsx
//
// A simple vertical stack of milestone rows, replacing the old
// PromiseDashboardCanvas's absolute-percentage-positioned timeline bar
// (PromiseMeter), whose fixed-size dots/pills collided once squeezed into a
// narrow panel. This scales to any width with no collision risk.

import { AlertTriangle, CheckCircle2, Circle } from "lucide-react";
import type { PromiseMilestone } from "@/types/order";

const toneDot: Record<PromiseMilestone["tone"], string> = {
  success: "bg-emerald-500 text-white",
  warning: "bg-amber-400 text-black",
  danger: "bg-rose-500 text-white",
  neutral: "bg-neutral-300 text-neutral-700",
  promise: "bg-neutral-900 text-white",
};

export function InlineDeliveryTimeline({
  milestones,
}: {
  milestones: PromiseMilestone[];
}) {
  const sortedMilestones = [...milestones].sort(
    (a, b) => a.position - b.position
  );

  return (
    <div className="space-y-2">
      {sortedMilestones.map((milestone) => (
        <div
          key={`${milestone.label}-${milestone.date}`}
          className="flex items-center gap-2.5"
        >
          <span
            className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${toneDot[milestone.tone]}`}
          >
            {milestone.tone === "warning" || milestone.tone === "danger" ? (
              <AlertTriangle size={11} />
            ) : milestone.tone === "neutral" ? (
              <Circle size={8} fill="currentColor" />
            ) : (
              <CheckCircle2 size={11} />
            )}
          </span>

          <p className="min-w-0 flex-1 truncate text-xs font-bold text-neutral-800">
            {milestone.tone === "promise" ? "Original promise" : milestone.label}
          </p>

          <p className="shrink-0 text-[11px] text-neutral-500">
            {milestone.date}
          </p>
        </div>
      ))}
    </div>
  );
}
