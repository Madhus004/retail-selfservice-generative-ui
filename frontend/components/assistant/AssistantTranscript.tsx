"use client";

import { useEffect, useRef } from "react";
import { A2UIRenderer } from "@/components/A2UIRenderer";
import { A2UIRendererV3 } from "@/components/A2UIRendererV3";
import { AssistantTypingIndicator } from "@/components/assistant/AssistantTypingIndicator";
import { useAssistant } from "@/components/assistant/AssistantProvider";
import { SuggestedActionChips } from "@/components/assistant/inline/SuggestedActionChips";
import type { A2UIComponent, AgentUIMode } from "@/lib/agent-api";
import type { A2UIComponentV2, V2ComponentType } from "@/lib/agent-api-v2";
import type { A2UIComponentV3 } from "@/lib/agent-api-v3";

export function AssistantTranscript() {
  const {
    transcript,
    isAgentLoading,
    loadingLabel,
    loadingOrderNumber,
    selectOrder,
    reportWrongDelivery,
    submitWrongDeliveryClaim,
    submitOrderCancellation,
    sendFreeText,
    resumeV2,
    resumeV3,
    whereIsMyOrder,
    cancelAnOrder,
  } = useAssistant();

  const bottomRef = useRef<HTMLDivElement>(null);
  const latestAssistantTurnRef = useRef<HTMLDivElement | null>(null);
  const previousTranscriptLengthRef = useRef(transcript.length);

  useEffect(() => {
    const grew = transcript.length > previousTranscriptLengthRef.current;
    previousTranscriptLengthRef.current = transcript.length;

    const latestTurn = transcript[transcript.length - 1];

    if (grew && latestTurn?.role === "assistant") {
      // Show the start of the new answer, not wherever its generated UI ends.
      latestAssistantTurnRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      return;
    }

    if (isAgentLoading) {
      // A new user turn just landed or a request just started — reveal the
      // typing indicator at the bottom.
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [transcript, isAgentLoading]);

  if (transcript.length === 0 && !isAgentLoading) {
    // A couple of starter phrases, not a permanent command menu — these
    // chips live inside the greeting itself and disappear the moment a
    // conversation actually starts (transcript.length > 0), the same way
    // the per-turn suggestedReplies chips below disappear once their turn
    // is no longer the latest one. That's the deliberate difference from
    // the static "Choose a support option" panel this replaced: an
    // agentic assistant offers a couple of starting points inline, it
    // doesn't keep a fixed button menu pinned on screen for the whole
    // conversation.
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center">
        <div>
          <p className="text-sm font-bold text-neutral-900">
            Hi! I’m Uni, your AI self-service associate.
          </p>
          <p className="mt-2 text-sm leading-6 text-neutral-500">
            Ask me about an order, delivery promise, or delivery issue.
          </p>
        </div>
        <SuggestedActionChips
          chips={[
            { label: "Where is my order?", onClick: whereIsMyOrder },
            { label: "Cancel an order", onClick: cancelAnOrder },
          ]}
        />
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
      {transcript.map((turn, index) => {
        const isLatestTurn = index === transcript.length - 1;

        return turn.role === "user" ? (
          <div key={turn.id} className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-black px-4 py-2.5 text-sm font-medium text-white">
              {turn.text}
            </div>
          </div>
        ) : (
          <div
            key={turn.id}
            ref={isLatestTurn ? latestAssistantTurnRef : undefined}
            className="space-y-3"
          >
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl rounded-tl-sm bg-neutral-100 px-4 py-2.5 text-sm leading-6 text-neutral-800">
                {turn.text}
              </div>
            </div>

            {turn.engine === "v3" ? (
              <A2UIRendererV3
                components={turn.a2ui as A2UIComponentV3[]}
                orders={turn.canvasData.orders ?? []}
                selectedOrder={turn.canvasData.selectedOrder ?? null}
                eligibleOrders={turn.canvasData.eligibleOrders ?? []}
                returnEligibleOrders={turn.canvasData.returnEligibleOrders ?? []}
                returnEligibility={turn.canvasData.returnEligibility ?? null}
                returnReasonOptions={turn.canvasData.returnReasonOptions}
                orderNumber={turn.orderNumber}
                // A structured resume (order/item/reason/method click,
                // Confirm/Decline) only ever makes sense against the
                // CURRENT pending interrupt on this thread — an older turn
                // whose own question has already been answered has no
                // live interrupt behind it anymore. Clicking one of its
                // cards would silently no-op (the graph has nothing to
                // resume, so it just echoes back the same final state —
                // the exact bug this closes: selecting a second order
                // card from an old "which order?" list, after the first
                // selection already resolved, replayed the first order's
                // answer instead of doing anything with the second). Once
                // superseded, a turn's cards render disabled rather than
                // silently misbehaving.
                isAgentLoading={isAgentLoading || !isLatestTurn}
                loadingOrderNumber={loadingOrderNumber}
                onSelectOrder={
                  isLatestTurn
                    ? (order) =>
                        resumeV3(
                          { type: "ORDER_SELECTED", payload: { orderNumber: order.orderNumber } },
                          `Order ${order.orderNumber}`
                        )
                    : () => {}
                }
                onResumeV3={isLatestTurn ? resumeV3 : () => Promise.resolve("")}
              />
            ) : (
              <A2UIRenderer
                // Non-v3 turns never carry a V3ComponentType/A2UIComponentV3
                // — the `engine !== "v3"` branch above already guarantees
                // this at runtime, but TranscriptTurn's uiMode/a2ui fields
                // aren't discriminated on `engine` at the type level, so a
                // cast documents what's already true rather than widening
                // A2UIRenderer's own props to accept V3's catalog too.
                uiMode={turn.uiMode as AgentUIMode | V2ComponentType}
                components={turn.a2ui as (A2UIComponent | A2UIComponentV2)[]}
                selectedOrder={turn.canvasData.selectedOrder ?? null}
                orders={turn.canvasData.orders ?? []}
                isAgentLoading={isAgentLoading}
                loadingOrderNumber={loadingOrderNumber}
                claimResult={turn.canvasData.claimResult ?? null}
                eligibleOrders={turn.canvasData.eligibleOrders ?? []}
                cancellationResult={turn.canvasData.cancellationResult ?? null}
                returnEligibility={turn.canvasData.returnEligibility ?? null}
                returnReasonOptions={turn.canvasData.returnReasonOptions}
                orderNumber={turn.engine === "v2" ? turn.orderNumber : undefined}
                // V2 turns resolve an order-selection click into a structured,
                // typed resume on the same thread, never V1's free-text
                // convention and never a raw {selection:...} shape (2026-08
                // structured-interaction fix — the exact bug this replaced
                // synthesized "Track U-1001" prose that the agent then
                // misread as a request to track the order). V1 turns
                // (engine undefined) keep using the existing selectOrder
                // callback unchanged.
                onSelectOrder={
                  turn.engine === "v2"
                    ? (order) =>
                        resumeV2(
                          {
                            type: "ORDER_SELECTED",
                            capability: turn.capability ?? "ORDER_STATUS",
                            payload: { orderNumber: order.orderNumber },
                          },
                          `Order ${order.orderNumber}`
                        )
                    : selectOrder
                }
                onReportWrongDelivery={reportWrongDelivery}
                onSubmitWrongDeliveryClaim={submitWrongDeliveryClaim}
                onSubmitOrderCancellation={submitOrderCancellation}
                onResumeV2={resumeV2}
              />
            )}

            {isLatestTurn &&
              !isAgentLoading &&
              turn.suggestedReplies &&
              turn.suggestedReplies.length > 0 && (
                <SuggestedActionChips
                  chips={turn.suggestedReplies.map((label) => ({
                    label,
                    onClick: () => void sendFreeText(label),
                  }))}
                />
              )}
          </div>
        );
      })}

      {isAgentLoading && <AssistantTypingIndicator label={loadingLabel} />}

      <div ref={bottomRef} />
    </div>
  );
}
