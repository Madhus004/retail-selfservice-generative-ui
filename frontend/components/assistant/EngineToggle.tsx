// frontend/components/assistant/EngineToggle.tsx
//
// Dev-only toggle (plan section 27) between the V1 six-node pipeline and
// the V2 bounded autonomous agent, so both can be exercised against the
// identical customer message from the same running app without a dev-server
// restart — an env var would need one, a query param wouldn't survive a
// reload. Persists to localStorage (read fresh by AssistantProvider on
// every request, not just at mount) rather than React context, so this
// component and AssistantProvider stay fully decoupled.
"use client";

import { useSyncExternalStore } from "react";

export type UniEngine = "v1" | "v2" | "v3";

const ENGINE_STORAGE_KEY = "uni-engine";
const DEFAULT_ENGINE: UniEngine = "v1";
const ENGINE_CHANGE_EVENT = "uni-engine-change";

function readEngine(): UniEngine {
  if (typeof window === "undefined") return DEFAULT_ENGINE;

  try {
    const stored = window.localStorage.getItem(ENGINE_STORAGE_KEY);
    return stored === "v2" || stored === "v3" ? stored : DEFAULT_ENGINE;
  } catch {
    return DEFAULT_ENGINE;
  }
}

export function getEnginePreference(): UniEngine {
  return readEngine();
}

export function setEnginePreference(engine: UniEngine): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(ENGINE_STORAGE_KEY, engine);
    // Same-tab localStorage writes don't fire the native "storage" event
    // (only other tabs receive that) — this is what lets EngineToggle's
    // own subscribers re-render immediately after a click in this tab.
    window.dispatchEvent(new Event(ENGINE_CHANGE_EVENT));
  } catch {
    // localStorage may be unavailable (private browsing, quota) — non-critical.
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  window.addEventListener(ENGINE_CHANGE_EVENT, callback);

  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(ENGINE_CHANGE_EVENT, callback);
  };
}

function getServerSnapshot(): UniEngine {
  return DEFAULT_ENGINE;
}

// Absent from any real customer-facing build by default — only renders
// when explicitly opted into via this build flag.
const ENGINE_TOGGLE_ENABLED =
  process.env.NEXT_PUBLIC_ENABLE_ENGINE_TOGGLE === "true";

export function EngineToggle() {
  // useSyncExternalStore, not useState+useEffect — localStorage is an
  // external store, and this is React's dedicated API for subscribing to
  // one safely (correct SSR snapshot, no hydration-mismatch flash, no
  // setState-in-effect).
  const engine = useSyncExternalStore(subscribe, readEngine, getServerSnapshot);

  if (!ENGINE_TOGGLE_ENABLED) return null;

  return (
    <div
      role="group"
      aria-label="Uni engine"
      className="flex items-center gap-1 rounded-full border border-black/10 bg-neutral-50 p-1 text-[11px] font-black uppercase tracking-wide"
    >
      <button
        type="button"
        onClick={() => setEnginePreference("v1")}
        aria-pressed={engine === "v1"}
        className={`rounded-full px-2.5 py-1 transition ${
          engine === "v1" ? "bg-black text-white" : "text-neutral-500"
        }`}
      >
        V1
      </button>
      <button
        type="button"
        onClick={() => setEnginePreference("v2")}
        aria-pressed={engine === "v2"}
        className={`rounded-full px-2.5 py-1 transition ${
          engine === "v2" ? "bg-black text-white" : "text-neutral-500"
        }`}
      >
        V2
      </button>
      <button
        type="button"
        onClick={() => setEnginePreference("v3")}
        aria-pressed={engine === "v3"}
        className={`rounded-full px-2.5 py-1 transition ${
          engine === "v3" ? "bg-black text-white" : "text-neutral-500"
        }`}
      >
        V3
      </button>
    </div>
  );
}
