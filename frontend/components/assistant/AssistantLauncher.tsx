"use client";

import { Sparkles } from "lucide-react";
import { useAssistant } from "@/components/assistant/AssistantProvider";

export function AssistantLauncher() {
  const { visibility, transcript, open } = useAssistant();

  if (visibility === "open") {
    return null;
  }

  const hasHistory = transcript.length > 0;

  return (
    <button
      onClick={open}
      className="fixed bottom-6 right-6 z-30 flex items-center gap-2 rounded-full bg-black px-5 py-4 text-sm font-black text-white shadow-xl shadow-black/20 transition hover:scale-105"
    >
      <Sparkles size={18} />
      {hasHistory ? "Continue with Uni" : "Chat with Uni"}
    </button>
  );
}
