// frontend/components/assistant/inline/InlineWelcome.tsx
//
// Panel-native replacement for WelcomeCanvas. Deliberately minimal — the
// transcript's own empty state already carries the greeting, so this only
// renders for genuine unclear-intent turns. Any quick-action chip for this
// turn comes from the backend's deterministic suggestedReplies, rendered
// generically by AssistantTranscript — this component just shows the text.

export function InlineWelcome() {
  return (
    <div className="rounded-2xl border border-black/10 bg-[#fbfaf7] p-3">
      <p className="text-sm leading-5 text-neutral-600">
        I can help with order tracking, delivery promises, and delivery
        issues.
      </p>
    </div>
  );
}
