// frontend/components/assistant/inline/InlineClaimForm.tsx
//
// Panel-native replacement for WrongDeliveryClaimCanvas. Same fields and
// submit-gating logic, compact single-column spacing/typography.
"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import type { OrderScenario, WrongDeliveryClaimDraft } from "@/types/order";

export function InlineClaimForm({
  order,
  onSubmitClaim,
}: {
  order: OrderScenario | null;
  onSubmitClaim: (claim: WrongDeliveryClaimDraft) => void;
}) {
  const firstPackage = order?.packages?.[0];

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
    <div className="rounded-2xl border border-black/10 bg-white p-3">
      <p className="mb-2 text-xs font-black uppercase tracking-[0.18em] text-neutral-400">
        Wrong-delivery claim
      </p>

      <label className="mb-2 block">
        <span className="mb-1 block text-xs font-bold text-neutral-700">
          What happened?
        </span>
        <textarea
          value={issueDescription}
          onChange={(event) => setIssueDescription(event.target.value)}
          className="min-h-20 w-full resize-none rounded-xl border border-black/10 bg-[#fbfaf7] p-2.5 text-xs leading-5 text-neutral-700 outline-none focus:border-black/30"
        />
      </label>

      <label className="mb-3 block">
        <span className="mb-1 block text-xs font-bold text-neutral-700">
          Preferred contact
        </span>
        <select
          value={preferredContactMethod}
          onChange={(event) =>
            setPreferredContactMethod(event.target.value as "email" | "phone")
          }
          className="w-full rounded-xl border border-black/10 bg-[#fbfaf7] p-2.5 text-xs font-bold text-neutral-700 outline-none focus:border-black/30"
        >
          <option value="email">Email</option>
          <option value="phone">Phone</option>
        </select>
      </label>

      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        className="flex w-full items-center justify-center gap-2 rounded-full bg-black px-4 py-2.5 text-xs font-black text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
      >
        <CheckCircle2 size={14} />
        Submit claim
      </button>
    </div>
  );
}
