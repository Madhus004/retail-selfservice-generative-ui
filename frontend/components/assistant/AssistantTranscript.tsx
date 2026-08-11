"use client";

import { useEffect, useRef } from "react";
import { A2UIRenderer } from "@/components/A2UIRenderer";
import { AssistantTypingIndicator } from "@/components/assistant/AssistantTypingIndicator";
import { useAssistant } from "@/components/assistant/AssistantProvider";
import { SuggestedActionChips } from "@/components/assistant/inline/SuggestedActionChips";

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
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-10 text-center">
        <div>
          <p className="text-sm font-bold text-neutral-900">
            Hi! I’m Uni, your AI self-service associate.
          </p>
          <p className="mt-2 text-sm leading-6 text-neutral-500">
            Ask me about an order, delivery promise, or delivery issue.
          </p>
        </div>
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

            <A2UIRenderer
              uiMode={turn.uiMode}
              components={turn.a2ui}
              selectedOrder={turn.canvasData.selectedOrder ?? null}
              orders={turn.canvasData.orders ?? []}
              isAgentLoading={isAgentLoading}
              loadingOrderNumber={loadingOrderNumber}
              claimResult={turn.canvasData.claimResult ?? null}
              eligibleOrders={turn.canvasData.eligibleOrders ?? []}
              cancellationResult={turn.canvasData.cancellationResult ?? null}
              onSelectOrder={selectOrder}
              onReportWrongDelivery={reportWrongDelivery}
              onSubmitWrongDeliveryClaim={submitWrongDeliveryClaim}
              onSubmitOrderCancellation={submitOrderCancellation}
            />

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
