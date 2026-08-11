import { describe, expect, it } from "vitest";
import {
  assistantReducer,
  initialAssistantState,
  type TranscriptTurn,
} from "@/lib/assistant-reducer";

describe("assistantReducer", () => {
  it("opens on OPEN and hides on MINIMIZE without touching the transcript", () => {
    const turn: TranscriptTurn = {
      role: "user",
      id: "u1",
      text: "Where is my order?",
      ts: "2026-01-01T00:00:00.000Z",
    };

    let state = assistantReducer(initialAssistantState, { type: "OPEN" });
    expect(state.visibility).toBe("open");

    state = assistantReducer(state, {
      type: "SEND_MESSAGE",
      turn,
      loadingLabel: "Checking your recent orders...",
    });

    state = assistantReducer(state, { type: "MINIMIZE" });
    expect(state.visibility).toBe("minimized");
    expect(state.transcript).toEqual([turn]);

    state = assistantReducer(state, { type: "OPEN" });
    expect(state.visibility).toBe("open");
    expect(state.transcript).toEqual([turn]);
  });

  it("CLOSE ends the session: clears the transcript and loading state, unlike MINIMIZE", () => {
    const turn: TranscriptTurn = {
      role: "user",
      id: "u1",
      text: "Where is my order?",
      ts: "2026-01-01T00:00:00.000Z",
    };

    let state = assistantReducer(initialAssistantState, { type: "OPEN" });
    state = assistantReducer(state, {
      type: "SEND_MESSAGE",
      turn,
      loadingLabel: "Checking your recent orders...",
    });

    expect(state.transcript).toHaveLength(1);
    expect(state.isAgentLoading).toBe(true);

    state = assistantReducer(state, { type: "CLOSE" });

    expect(state).toEqual(initialAssistantState);
    expect(state.transcript).toHaveLength(0);
    expect(state.isAgentLoading).toBe(false);
  });

  it("tracks loading state across a send/receive cycle", () => {
    const userTurn: TranscriptTurn = {
      role: "user",
      id: "u1",
      text: "Where is my order?",
      ts: "2026-01-01T00:00:00.000Z",
    };

    let state = assistantReducer(initialAssistantState, {
      type: "SEND_MESSAGE",
      turn: userTurn,
      loadingLabel: "Checking your recent orders...",
    });

    expect(state.isAgentLoading).toBe(true);
    expect(state.loadingLabel).toBe("Checking your recent orders...");
    expect(state.transcript).toHaveLength(1);

    const assistantTurn: TranscriptTurn = {
      role: "assistant",
      id: "a1",
      text: "Here are your recent orders.",
      uiMode: "orderSelection",
      a2ui: [{ type: "orderSelection" }],
      canvasData: {},
      ts: "2026-01-01T00:00:01.000Z",
    };

    state = assistantReducer(state, {
      type: "RECEIVE_RESPONSE",
      turn: assistantTurn,
    });

    expect(state.isAgentLoading).toBe(false);
    expect(state.loadingLabel).toBeNull();
    expect(state.transcript).toHaveLength(2);
  });

  it("restores a persisted session via HYDRATE without touching loading state", () => {
    const transcript: TranscriptTurn[] = [
      { role: "user", id: "u1", text: "hi", ts: "2026-01-01T00:00:00.000Z" },
    ];

    const state = assistantReducer(initialAssistantState, {
      type: "HYDRATE",
      visibility: "minimized",
      transcript,
    });

    expect(state.visibility).toBe("minimized");
    expect(state.transcript).toEqual(transcript);
    expect(state.isAgentLoading).toBe(false);
  });
});
