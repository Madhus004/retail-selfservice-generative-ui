// frontend/components/assistant/AssistantTypingIndicator.tsx

import { Loader2 } from "lucide-react";

export function AssistantTypingIndicator({ label }: { label: string | null }) {
  return (
    <div className="flex items-center gap-2 px-1 text-sm text-neutral-500">
      <Loader2 size={14} className="animate-spin" />
      <span>{label ?? "Uni is looking into this..."}</span>
    </div>
  );
}
