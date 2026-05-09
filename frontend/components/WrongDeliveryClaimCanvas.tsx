// frontend/components/WrongDeliveryClaimCanvas.tsx
"use client";

import { useState } from "react";
import { AlertTriangle, Camera, CheckCircle2, FileText } from "lucide-react";
import type { OrderScenario, WrongDeliveryClaimDraft } from "@/types/order";

export function WrongDeliveryClaimCanvas({
  order,
  onBackToDashboard,
  onSubmitClaim,
}: {
  order: OrderScenario | null;
  onBackToDashboard: () => void;
  onSubmitClaim: (claim: WrongDeliveryClaimDraft) => void;
}) {
  const firstPackage = order?.packages?.[0];
  const deliveryProof = firstPackage?.deliveryProof;

  const [issueDescription, setIssueDescription] = useState(
    "The tracking says delivered, but this was not delivered to my address."
  );
  const [preferredContactMethod, setPreferredContactMethod] =
    useState<"email" | "phone">("email");

  const canSubmit = Boolean(order?.orderNumber && issueDescription.trim());

  const handleSubmit = () => {
    if (!order || !canSubmit) return;

    onSubmitClaim({
      orderNumber: order.orderNumber,
      packageNumber: firstPackage?.packageNumber,
      issueDescription: issueDescription.trim(),
      preferredContactMethod,
    });
  };

  return (
    <div className="min-h-full rounded-[1.5rem] bg-white p-8">
      <button
        onClick={onBackToDashboard}
        className="mb-6 rounded-full border border-black/10 bg-white px-4 py-2 text-sm font-bold text-neutral-700 transition hover:bg-neutral-50"
      >
        ← Back to order details
      </button>

      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="mb-3 text-xs font-black uppercase tracking-[0.28em] text-neutral-400">
            Wrong-delivery claim
          </p>
          <h2 className="text-4xl font-black tracking-[-0.055em] text-neutral-950">
            Let’s investigate this delivery.
          </h2>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-neutral-600">
            We’ll collect a few details and send this to the Unicorn service
            team for review. You’ll receive an update within 1–2 days.
          </p>
        </div>

        <div className="rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-black text-amber-700">
          Claim review
        </div>
      </div>

      {order && (
        <div className="mb-6 rounded-[2rem] border border-black/10 bg-[#fbfaf7] p-6">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-black text-white">
              <AlertTriangle size={20} />
            </div>

            <div>
              <p className="text-xs font-black uppercase tracking-[0.24em] text-neutral-400">
                Order under review
              </p>
              <h3 className="mt-1 text-2xl font-black tracking-[-0.04em]">
                Order {order.orderNumber}
              </h3>
              <p className="mt-2 text-sm leading-6 text-neutral-600">
                {order.customerSummary}
              </p>
            </div>
          </div>
        </div>
      )}

      {deliveryProof && (
        <div className="mb-6 rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-black text-white">
              <Camera size={18} />
            </div>
            <div>
              <h3 className="text-xl font-black tracking-[-0.04em]">
                Delivery proof on file
              </h3>
              <p className="text-sm text-neutral-500">
                We’ll include this proof photo information with the claim.
              </p>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-5">
              <p className="text-xs font-black uppercase tracking-[0.24em] text-neutral-400">
                Package
              </p>
              <p className="mt-2 text-lg font-black">
                Package #{firstPackage?.packageNumber}
              </p>
            </div>

            <div className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-5">
              <p className="text-xs font-black uppercase tracking-[0.24em] text-neutral-400">
                Delivered
              </p>
              <p className="mt-2 text-lg font-black">
                {deliveryProof.deliveredAt}
              </p>
            </div>

            <div className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-5">
              <p className="text-xs font-black uppercase tracking-[0.24em] text-neutral-400">
                Location note
              </p>
              <p className="mt-2 text-lg font-black">
                {deliveryProof.locationNote}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-[2rem] border border-black/10 bg-white p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-black text-white">
            <FileText size={18} />
          </div>
          <div>
            <h3 className="text-xl font-black tracking-[-0.04em]">
              Claim details
            </h3>
            <p className="text-sm text-neutral-500">
              Tell us what happened so the service team can investigate.
            </p>
          </div>
        </div>

        <div className="grid gap-4">
          <label className="grid gap-2">
            <span className="text-sm font-black text-neutral-800">
              What happened?
            </span>
            <textarea
              value={issueDescription}
              onChange={(event) => setIssueDescription(event.target.value)}
              className="min-h-28 resize-none rounded-3xl border border-black/10 bg-white p-4 text-sm leading-6 text-neutral-700 outline-none transition focus:border-black/30 focus:ring-4 focus:ring-black/5"
              placeholder="Tell us what happened with this delivery..."
            />
          </label>

          <label className="grid gap-2">
            <span className="text-sm font-black text-neutral-800">
              Preferred contact method
            </span>
            <select
              value={preferredContactMethod}
              onChange={(event) =>
                setPreferredContactMethod(event.target.value as "email" | "phone")
              }
              className="rounded-2xl border border-black/10 bg-white p-4 text-sm font-bold text-neutral-700 outline-none transition focus:border-black/30 focus:ring-4 focus:ring-black/5"
            >
              <option value="email">Email</option>
              <option value="phone">Phone</option>
            </select>
          </label>

          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="mt-2 flex items-center justify-center gap-2 rounded-full bg-black px-6 py-4 text-sm font-black text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
          >
            <CheckCircle2 size={18} />
            Submit claim
          </button>
        </div>
      </div>
    </div>
  );
}