// frontend/components/assistant/inline/InlineConfirmationCardV3.tsx
//
// V3-only. Generic PENDING/CONFIRMED display for V3's ConfirmationCard a2ui
// type — one component for every sensitive action (CANCELLATION today,
// RETURNS too), driven entirely by the mandatory UI's own props (never
// validated against an agent proposal — this is the code-owned half of
// A2UI, by construction; see agent/v3/ui/catalog.py's build_mandatory_ui).
// Adapted from InlineConfirmationCard (V2) — same UI, but the resume
// payload carries no "capability" field.
"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import type { ConfirmationResumeV3 } from "@/lib/agent-api-v3";

type PendingActionSummary = {
  actionId: string;
  actionType: string;
};

function summarizeAction(data: Record<string, unknown>): string[] {
  const lines: string[] = [];

  const items =
    (data.returnedItems as
      | { itemName: string; color: string; size: string; quantity: number }[]
      | undefined) ??
    (data.cancelledItems as
      | { itemName: string; color: string; size: string; quantity: number }[]
      | undefined);

  if (Array.isArray(items)) {
    for (const item of items) {
      lines.push(`${item.quantity} × ${item.itemName} (${item.color}, ${item.size})`);
    }
  }

  if (typeof data.reason === "string" && data.reason) {
    lines.push(`Reason: ${data.reason}`);
  }

  if (typeof data.refundEstimate === "number") {
    lines.push(`Estimated refund: $${data.refundEstimate.toFixed(2)}`);
  }

  if (typeof data.resultingOrderStatus === "string") {
    lines.push(`Order status: ${data.resultingOrderStatus}`);
  }

  return lines;
}

export function InlineConfirmationCardV3({
  phase,
  preview,
  pending,
  result,
  isAgentLoading,
  onResumeV3,
}: {
  phase: "PENDING" | "CONFIRMED";
  preview?: Record<string, unknown> | null;
  pending?: PendingActionSummary | null;
  result?: Record<string, unknown> | null;
  isAgentLoading: boolean;
  onResumeV3?: (resume: ConfirmationResumeV3, userFacingLabel: string) => void;
}) {
  const data = (phase === "PENDING" ? preview : result) ?? {};
  const orderNumber = typeof data.orderNumber === "string" ? data.orderNumber : undefined;
  const summaryLines = summarizeAction(data);

  if (phase === "CONFIRMED") {
    return (
      <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
            <CheckCircle2 size={14} />
          </div>
          <p className="text-sm font-black tracking-[-0.02em] text-neutral-950">
            {orderNumber ? `Order ${orderNumber} updated` : "Submitted"}
          </p>
        </div>

        {summaryLines.length > 0 && (
          <div className="mt-2 space-y-1">
            {summaryLines.map((line, index) => (
              <p key={index} className="text-xs text-neutral-700">
                {line}
              </p>
            ))}
          </div>
        )}
      </div>
    );
  }

  const handleDecision = (accepted: boolean) => {
    if (!pending || !onResumeV3) return;

    onResumeV3(
      {
        confirmation: {
          actionId: pending.actionId,
          actionType: pending.actionType,
          accepted,
        },
      },
      accepted ? "Confirm" : "Decline"
    );
  };

  return (
    <div className="rounded-2xl border border-black/10 bg-white p-3">
      <p className="text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
        {orderNumber ? `Order ${orderNumber}` : "Please confirm"}
      </p>

      {summaryLines.length > 0 && (
        <div className="mt-2 space-y-1">
          {summaryLines.map((line, index) => (
            <p key={index} className="text-sm text-neutral-800">
              {line}
            </p>
          ))}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => handleDecision(true)}
          disabled={isAgentLoading || !pending}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-black px-4 py-2.5 text-xs font-black text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
        >
          <CheckCircle2 size={14} /> Confirm
        </button>
        <button
          type="button"
          onClick={() => handleDecision(false)}
          disabled={isAgentLoading || !pending}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-full border border-black/10 px-4 py-2.5 text-xs font-black text-neutral-700 transition hover:bg-neutral-50 disabled:cursor-not-allowed disabled:text-neutral-300"
        >
          <XCircle size={14} /> Decline
        </button>
      </div>
    </div>
  );
}
