import { describe, expect, it } from "vitest";

import {
  appendUserMessage,
  chatReducer,
  initialChatState,
} from "@/lib/chatReducer";

describe("chatReducer", () => {
  it("seeds from history", () => {
    const state = initialChatState([{ role: "user", content: "hi" }]);
    expect(state.messages).toHaveLength(1);
    expect(state.streaming).toBe(false);
  });

  it("appends a user message", () => {
    const state = appendUserMessage(initialChatState([]), "hello");
    expect(state.messages).toEqual([{ role: "user", content: "hello" }]);
  });

  it("folds start -> stream -> end into one assistant message", () => {
    let state = appendUserMessage(initialChatState([]), "q");
    state = chatReducer(state, { type: "start", content: "..." });
    expect(state.streaming).toBe(true);
    state = chatReducer(state, { type: "stream", content: "Hello" });
    state = chatReducer(state, { type: "stream", content: " world" });
    state = chatReducer(state, { type: "end", content: "done" });
    expect(state.streaming).toBe(false);
    const assistant = state.messages[state.messages.length - 1];
    expect(assistant).toEqual({ role: "assistant", content: "Hello world" });
  });

  it("records error frames without dropping the thread", () => {
    let state = appendUserMessage(initialChatState([]), "q");
    state = chatReducer(state, { type: "error", content: "boom" });
    expect(state.error).toBe("boom");
    expect(state.streaming).toBe(false);
    expect(state.messages).toHaveLength(1);
  });
});
