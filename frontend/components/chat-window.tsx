"use client";

import { useEffect, useReducer, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getMessages } from "@/lib/api";
import {
  appendUserMessage,
  chatReducer,
  initialChatState,
  type ChatState,
} from "@/lib/chatReducer";
import { openChatSocket, type ChatSocketHandlers } from "@/lib/ws";
import type { ChatFrame } from "@/lib/types";

type SocketFactory = (
  userId: string,
  conversationId: string,
  handlers: ChatSocketHandlers,
) => { send: (message: string) => void; close: () => void };

const EXAMPLE_PROMPTS = [
  "What changed in my feed today?",
  "Which watched suppliers need attention?",
  "Summarize the top tariff signals.",
];

export function ChatWindow({
  userId,
  conversationId,
  socketFactory = openChatSocket,
}: {
  userId: string;
  conversationId: string;
  socketFactory?: SocketFactory;
}) {
  const [state, dispatch] = useReducer(
    (
      s: ChatState,
      action:
        | { kind: "frame"; frame: ChatFrame }
        | { kind: "user"; content: string }
        | { kind: "reset"; next: ChatState },
    ) => {
      if (action.kind === "frame") return chatReducer(s, action.frame);
      if (action.kind === "user") return appendUserMessage(s, action.content);
      return action.next;
    },
    initialChatState([]),
  );
  const [draft, setDraft] = useState("");
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<{ send: (m: string) => void; close: () => void } | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let active = true;
    getMessages(conversationId).then((res) => {
      if (active) dispatch({ kind: "reset", next: initialChatState(res.messages) });
    });

    const socket = socketFactory(userId, conversationId, {
      onFrame: (frame) => dispatch({ kind: "frame", frame }),
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onError: () => setConnected(false),
    });
    socketRef.current = socket;

    return () => {
      active = false;
      socket.close();
    };
  }, [userId, conversationId, socketFactory]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [state.messages]);

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    dispatch({ kind: "user", content: trimmed });
    socketRef.current?.send(trimmed);
    setDraft("");
  };

  const isEmpty = state.messages.length === 0;
  const last = state.messages[state.messages.length - 1];
  const awaitingReply = state.streaming && last?.role === "assistant" && last.content === "";

  return (
    <div className="flex h-[72vh] min-h-[580px] flex-col rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <h1 className="text-base font-semibold text-slate-950">Procurement assistant</h1>
          <p className="mt-0.5 text-xs text-slate-500">Grounded in your saved preferences and feed.</p>
        </div>
        <span className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-500">
          <span
            className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-slate-300"}`}
            aria-hidden
          />
          {connected ? "Connected" : "Connecting…"}
        </span>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50/70 px-4 py-4">
        {isEmpty ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <p className="text-sm font-semibold text-slate-800">Ask about your latest signals</p>
            <p className="mt-1 max-w-sm text-sm leading-6 text-slate-500">
              The assistant uses your preferences and visible feed context.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {EXAMPLE_PROMPTS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => send(p)}
                  disabled={!connected}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-950 disabled:opacity-50"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : (
          state.messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[78%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-6 shadow-sm ${
                  m.role === "user"
                    ? "bg-slate-950 text-white shadow-slate-300/30"
                    : "border border-slate-200 bg-white text-slate-800 shadow-slate-200/70"
                }`}
              >
                {m.content ||
                  (awaitingReply && i === state.messages.length - 1 ? (
                    <span className="inline-flex gap-1 py-1" aria-label="Assistant is typing">
                      <Dot /> <Dot /> <Dot />
                    </span>
                  ) : null)}
              </div>
            </div>
          ))
        )}
        {state.error ? (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{state.error}</p>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex items-end gap-2 border-t border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <Textarea
          aria-label="Message"
          placeholder="Ask about your feed..."
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
          className="max-h-32 flex-1 resize-none"
        />
        <Button type="submit" disabled={!draft.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}

function Dot() {
  return <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />;
}
