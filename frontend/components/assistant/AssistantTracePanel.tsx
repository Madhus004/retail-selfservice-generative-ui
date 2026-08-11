// frontend/components/assistant/AssistantTracePanel.tsx
//
// Opt-in developer/demo view of the raw AG-UI-style SSE events (intent
// detection, tool calls, A2UI selection, etc.) for the most recent request.
// Repurposes AgentProgressPanel.tsx's step-list idea, restyled compact for
// the panel instead of a full-canvas hero takeover.

import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import type { AgentTraceEntry } from "@/components/assistant/AssistantProvider";

export function AssistantTracePanel({ trace }: { trace: AgentTraceEntry[] }) {
  if (trace.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-black/15 bg-neutral-50 px-3 py-2.5 text-xs leading-5 text-neutral-500">
        No agent trace yet — send a message to see intent detection, tool
        calls, and A2UI selection events here.
      </div>
    );
  }

  return (
    <div className="space-y-1.5 rounded-2xl border border-black/10 bg-neutral-50 p-3">
      {trace.map((event) => (
        <div key={event.id} className="flex items-center gap-2 text-xs">
          {event.status === "error" ? (
            <AlertTriangle size={12} className="shrink-0 text-rose-600" />
          ) : event.status === "complete" ? (
            <CheckCircle2 size={12} className="shrink-0 text-emerald-600" />
          ) : (
            <Loader2 size={12} className="shrink-0 animate-spin text-neutral-500" />
          )}

          <span className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-neutral-400">
            {event.type}
          </span>

          <span className="truncate text-neutral-700">{event.label}</span>
        </div>
      ))}
    </div>
  );
}
