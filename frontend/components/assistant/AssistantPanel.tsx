"use client";

import { useState, type FormEvent } from "react";
import { ChevronDown, ChevronRight, Minus, Send, X } from "lucide-react";
import { useAssistant } from "@/components/assistant/AssistantProvider";
import { AssistantTracePanel } from "@/components/assistant/AssistantTracePanel";
import { AssistantTranscript } from "@/components/assistant/AssistantTranscript";
import { EngineToggle } from "@/components/assistant/EngineToggle";

export function AssistantPanel() {
  const { visibility, isAgentLoading, sendFreeText, minimize, close, agentTrace } =
    useAssistant();
  const [draft, setDraft] = useState("");
  const [isConfirmingClose, setIsConfirmingClose] = useState(false);
  const [showTrace, setShowTrace] = useState(false);

  const isOpen = visibility === "open";

  const handleMinimize = () => {
    setIsConfirmingClose(false);
    minimize();
  };

  const handleConfirmClose = () => {
    setIsConfirmingClose(false);
    close();
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();

    const message = draft.trim();
    if (!message || isAgentLoading) return;

    setDraft("");
    void sendFreeText(message);
  };

  return (
    <aside
      aria-hidden={!isOpen}
      className={`h-screen shrink-0 overflow-hidden border-l border-black/10 bg-white transition-[width] duration-200 ease-out ${
        isOpen ? "w-full sm:w-[420px]" : "w-0"
      }`}
    >
      <div className="flex h-full w-full flex-col sm:w-[420px]">
        <div className="flex items-center justify-between border-b border-black/10 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-black text-sm font-black text-white">
              U
            </div>
            <div>
              <p className="text-sm font-black tracking-[-0.02em]">
                Uni at Your Assistance
              </p>
              <p className="text-xs font-medium text-neutral-500">
                AI self-service associate
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <EngineToggle />
            <button
              onClick={handleMinimize}
              aria-label="Minimize assistant"
              className="rounded-full p-2 text-neutral-500 hover:bg-neutral-100"
            >
              <Minus size={16} />
            </button>
            <button
              onClick={() => setIsConfirmingClose(true)}
              aria-label="Close assistant"
              className="rounded-full p-2 text-neutral-500 hover:bg-neutral-100"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {isConfirmingClose ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-8 text-center">
            <p className="text-sm font-black text-neutral-900">
              End this chat?
            </p>
            <p className="text-sm leading-5 text-neutral-500">
              Your conversation will be cleared. Next time you open Uni,
              you&apos;ll start a new chat.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setIsConfirmingClose(false)}
                className="rounded-full border border-black/10 px-4 py-2 text-sm font-bold text-neutral-700 transition hover:bg-neutral-50"
              >
                Keep chatting
              </button>
              <button
                onClick={handleConfirmClose}
                className="rounded-full bg-black px-4 py-2 text-sm font-bold text-white transition hover:bg-neutral-800"
              >
                End chat
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="border-b border-black/10 px-5 py-3">
              <button
                onClick={() => setShowTrace((value) => !value)}
                className="flex items-center gap-1.5 text-[11px] font-black uppercase tracking-[0.18em] text-neutral-400 transition hover:text-neutral-600"
              >
                {showTrace ? (
                  <ChevronDown size={12} />
                ) : (
                  <ChevronRight size={12} />
                )}
                Show agent trace
              </button>

              {showTrace && (
                <div className="mt-3">
                  <AssistantTracePanel trace={agentTrace} />
                </div>
              )}
            </div>

            <AssistantTranscript />

            <form
              onSubmit={handleSubmit}
              className="flex items-center gap-2 border-t border-black/10 px-4 py-3"
            >
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask Uni a question..."
                disabled={isAgentLoading}
                className="flex-1 rounded-full border border-black/10 bg-neutral-50 px-4 py-2.5 text-sm outline-none focus:border-black/30"
              />
              <button
                type="submit"
                disabled={isAgentLoading || !draft.trim()}
                aria-label="Send"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-black text-white disabled:opacity-30"
              >
                <Send size={16} />
              </button>
            </form>
          </>
        )}
      </div>
    </aside>
  );
}
