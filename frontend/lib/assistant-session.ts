// frontend/lib/assistant-session.ts

import type { AssistantVisibility, TranscriptTurn } from "@/lib/assistant-reducer";

const SESSION_STORAGE_KEY = "uni-assistant-session";
const SCHEMA_VERSION = 1;

type PersistedAssistantSession = {
  schemaVersion: number;
  status: AssistantVisibility;
  transcript: TranscriptTurn[];
};

export function loadAssistantSession(): PersistedAssistantSession | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw) as PersistedAssistantSession;

    if (parsed.schemaVersion !== SCHEMA_VERSION) {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
}

export function saveAssistantSession(session: {
  status: AssistantVisibility;
  transcript: TranscriptTurn[];
}): void {
  if (typeof window === "undefined") return;

  try {
    const payload: PersistedAssistantSession = {
      schemaVersion: SCHEMA_VERSION,
      status: session.status,
      transcript: session.transcript,
    };

    window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // sessionStorage may be unavailable (private browsing, quota) — non-critical, fail silently.
  }
}
