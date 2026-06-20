import type { ChatFrame, ChatMessage } from "@/lib/types";

export interface ChatState {
  messages: ChatMessage[];
  streaming: boolean;
  error: string | null;
}

export function initialChatState(history: ChatMessage[]): ChatState {
  return { messages: [...history], streaming: false, error: null };
}

export function appendUserMessage(state: ChatState, content: string): ChatState {
  return {
    ...state,
    error: null,
    messages: [...state.messages, { role: "user", content }],
  };
}

export function chatReducer(state: ChatState, frame: ChatFrame): ChatState {
  switch (frame.type) {
    case "start":
      return {
        ...state,
        streaming: true,
        error: null,
        messages: [...state.messages, { role: "assistant", content: "" }],
      };
    case "stream": {
      const messages = [...state.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, content: last.content + frame.content };
      }
      return { ...state, messages };
    }
    case "end":
      return { ...state, streaming: false };
    case "error":
      return { ...state, streaming: false, error: frame.content };
    default:
      return state;
  }
}
