// frontend/components/assistant/inline/SuggestedActionChips.tsx
//
// Shared pill-button row. Used today by InlineOrderList/InlineWelcome for
// client-only quick actions, and designed to be reused later by the
// backend-driven `suggestedReplies` field (Phase 4) without rework.

export type SuggestedActionChip = {
  label: string;
  onClick: () => void;
};

export function SuggestedActionChips({
  chips,
}: {
  chips: SuggestedActionChip[];
}) {
  if (chips.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <button
          key={chip.label}
          onClick={chip.onClick}
          className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-bold text-neutral-700 transition hover:border-black/30 hover:bg-neutral-50"
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
