// frontend/components/AgentProgressPanel.tsx

import { CheckCircle2, Loader2, Sparkles } from "lucide-react";
import type { AgentStep } from "@/lib/agent-api";

export function AgentProgressPanel({ steps }: { steps: AgentStep[] }) {
  return (
    <div className="flex min-h-full items-center justify-center rounded-[1.5rem] bg-white p-8">
      <div className="w-full max-w-3xl rounded-[2rem] border border-black/10 bg-[#fbfaf7] p-8 shadow-sm">
        <div className="mb-6 flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-black text-white">
            <Sparkles size={20} />
          </div>

          <div>
            <p className="mb-2 text-xs font-black uppercase tracking-[0.28em] text-neutral-400">
              AG-UI-style agent events
            </p>
            <h2 className="text-3xl font-black tracking-[-0.055em] text-neutral-950">
              Uni is reviewing your request.
            </h2>
            <p className="mt-3 text-sm leading-6 text-neutral-600">
              The chat and workspace are being updated from one agent
              interaction. Progress events stream first, then the final A2UI
              workspace renders.
            </p>
          </div>
        </div>

        <div className="grid gap-3">
          {steps.map((step, index) => (
            <div
              key={`${step.label}-${index}`}
              className="flex items-center gap-3 rounded-2xl border border-black/10 bg-white p-4"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-100">
                {step.status === "complete" ? (
                  <CheckCircle2 size={17} className="text-emerald-600" />
                ) : step.status === "error" ? (
                  <CheckCircle2 size={17} className="text-rose-600" />
                ) : (
                  <Loader2 size={17} className="animate-spin text-neutral-600" />
                )}
              </div>

              <p className="text-sm font-bold text-neutral-800">
                {step.label}
              </p>
            </div>
          ))}

          {steps.length === 0 && (
            <div className="flex items-center gap-3 rounded-2xl border border-black/10 bg-white p-4">
              <Loader2 size={17} className="animate-spin text-neutral-600" />
              <p className="text-sm font-bold text-neutral-800">
                Starting agent workflow...
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}