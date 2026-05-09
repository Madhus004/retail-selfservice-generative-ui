// frontend/components/ChatPanel.tsx
"use client";

import type { ReactNode } from "react";
import { Box, CheckCircle2, Loader2, MapPin, RotateCcw } from "lucide-react";
import { CopilotChat } from "@copilotkit/react-ui";
import type { AgentStep } from "@/lib/agent-api";

function SupportButton({
  icon,
  label,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center justify-between rounded-2xl border border-black/10 bg-white px-4 py-3 text-left text-sm font-black text-neutral-800 transition hover:border-black/30 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-400"
    >
      <span className="flex items-center gap-3">
        <span className={disabled ? "text-neutral-400" : "text-neutral-700"}>
          {icon}
        </span>
        {label}
      </span>

      {disabled ? (
        <span className="text-[10px] font-black uppercase tracking-widest text-neutral-400">
          Soon
        </span>
      ) : (
        <span className="text-neutral-500">→</span>
      )}
    </button>
  );
}

function CompactAgentActivity({
  isAgentLoading,
  steps,
}: {
  isAgentLoading: boolean;
  steps: AgentStep[];
}) {
  if (!isAgentLoading && steps.length === 0) {
    return null;
  }

  const visibleSteps = steps.slice(-4);

  return (
    <div className="px-5 py-4">
      <div className="rounded-3xl border border-black/10 bg-[#fbfaf7] p-4">
        <div className="mb-3 flex items-center gap-2">
          {isAgentLoading ? (
            <Loader2 size={16} className="animate-spin text-neutral-700" />
          ) : (
            <CheckCircle2 size={16} className="text-emerald-600" />
          )}

          <p className="text-xs font-black uppercase tracking-[0.18em] text-neutral-500">
            Agent activity
          </p>
        </div>

        <p className="mb-3 text-sm font-bold leading-5 text-neutral-900">
          {isAgentLoading
            ? "Uni is reviewing your request and updating the workspace."
            : "Workspace updated."}
        </p>

        <div className="grid gap-2">
          {visibleSteps.map((step, index) => (
            <div
              key={`${step.label}-${index}`}
              className="flex items-start gap-2 text-xs leading-5 text-neutral-600"
            >
              {step.status === "complete" ? (
                <CheckCircle2
                  size={14}
                  className="mt-0.5 shrink-0 text-emerald-600"
                />
              ) : step.status === "error" ? (
                <CheckCircle2
                  size={14}
                  className="mt-0.5 shrink-0 text-rose-600"
                />
              ) : (
                <Loader2
                  size={14}
                  className="mt-0.5 shrink-0 animate-spin text-neutral-500"
                />
              )}

              <span>{step.label}</span>
            </div>
          ))}

          {visibleSteps.length === 0 && (
            <div className="flex items-start gap-2 text-xs leading-5 text-neutral-600">
              <Loader2
                size={14}
                className="mt-0.5 shrink-0 animate-spin text-neutral-500"
              />
              <span>Starting agent workflow...</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ChatPanel({
  isAgentLoading,
  agentProgressSteps,
  onWhereIsMyOrder,
}: {
  isAgentLoading: boolean;
  agentProgressSteps: AgentStep[];
  onWhereIsMyOrder: () => void;
}) {
  return (
    <aside className="h-full overflow-y-auto border-r border-black/10 bg-white">
      <div className="border-b border-black/10 px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-black text-sm font-black text-white">
            U
          </div>
          <div>
            <h2 className="text-base font-black tracking-[-0.03em]">
              Uni at Your Assistance
            </h2>
            <p className="text-xs font-medium text-neutral-500">
              CopilotKit-powered support associate
            </p>
          </div>
        </div>
      </div>

      <div className="border-b border-black/10 px-6 py-5">
        <div className="rounded-3xl bg-neutral-50 p-4">
          <p className="text-sm leading-6 text-neutral-700">
            Hi! I’m Uni, your AI self-service associate. Ask me about an order,
            delivery promise, or delivery issue.
          </p>
        </div>
      </div>

      <div className="border-b border-black/10 p-5">
        <p className="mb-4 text-xs font-black uppercase tracking-[0.24em] text-neutral-400">
          Choose a support option
        </p>

        <div className="grid gap-3">
          <SupportButton
            icon={<Box size={16} />}
            label="Where is my order?"
            onClick={onWhereIsMyOrder}
          />

          <SupportButton
            icon={<RotateCcw size={16} />}
            label="Initiate a return"
            disabled
          />

          <SupportButton
            icon={<MapPin size={16} />}
            label="Update delivery address"
            disabled
          />
        </div>
      </div>

      <CompactAgentActivity
        isAgentLoading={isAgentLoading}
        steps={agentProgressSteps}
      />

      <div className="uni-copilot-chat px-5 pb-6">
        <CopilotChat
          className="min-h-[460px]"
          instructions="You are Uni, the customer support copilot for Unicorn Apparel. Important: for every customer request about orders, delivery promises, tracking, late delivery, weather delay, delivery proof, wrong delivery, claims, refunds, coupons, or service recovery, you must call the askUni action. Do not answer order-specific questions yourself. If the user says 'Where is my order?' or asks to track an order, call askUni with the exact user message. Do not ask for an order number first because askUni can retrieve recent orders and update the main workspace."
          labels={{
            title: "Uni Copilot",
            initial: "",
            placeholder: "Ask Uni a question...",
          }}
        />
      </div>
    </aside>
  );
}