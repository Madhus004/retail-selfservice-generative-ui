import { afterEach, describe, expect, it } from "vitest";
import { loadAssistantSession, saveAssistantSession } from "@/lib/assistant-session";

afterEach(() => {
  window.sessionStorage.clear();
});

describe("assistant session persistence", () => {
  it("round-trips status and transcript through sessionStorage", () => {
    saveAssistantSession({
      status: "minimized",
      transcript: [
        { role: "user", id: "u1", text: "hi", ts: "2026-01-01T00:00:00.000Z" },
      ],
    });

    const restored = loadAssistantSession();

    expect(restored?.status).toBe("minimized");
    expect(restored?.transcript).toHaveLength(1);
    expect(restored?.transcript[0]).toMatchObject({ role: "user", text: "hi" });
  });

  it("returns null when nothing has been stored", () => {
    expect(loadAssistantSession()).toBeNull();
  });

  it("returns null when the stored schema version does not match", () => {
    window.sessionStorage.setItem(
      "uni-assistant-session",
      JSON.stringify({ schemaVersion: 999, status: "open", transcript: [] })
    );

    expect(loadAssistantSession()).toBeNull();
  });
});
