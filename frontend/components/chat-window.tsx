"use client";

import { useEffect, useReducer, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
    (s: ChatState, action: { kind: "frame"; frame: ChatFrame } | { kind: "user"; content: string } | { kind: "reset"; next: ChatState }) => {
      if (action.kind === "frame") return chatReducer(s, action.frame);
      if (action.kind === "user") return appendUserMessage(s, action.content);
      return action.next;
    },
    initialChatState([]),
  );
  const [draft, setDraft] = useState("");
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<{ send: (m: string) => void; close: () => void } | null>(null);

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

  const onSend = () => {
    const text = draft.trim();
    if (!text) return;
    dispatch({ kind: "user", content: text });
    socketRef.current?.send(text);
    setDraft("");
  };

  return (
    <div className="flex h-[60vh] flex-col">
      <div className="mb-2 text-xs text-slate-500">
        {connected ? "● connected" : "○ offline"}
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto">
        {state.messages.map((m, i) => (
          <Card
            key={i}
            className={m.role === "user" ? "bg-slate-100" : "bg-white"}
          >
            <div className="text-xs uppercase text-slate-400">{m.role}</div>
            <div className="whitespace-pre-wrap text-sm">{m.content}</div>
          </Card>
        ))}
        {state.error ? <p className="text-sm text-red-700">{state.error}</p> : null}
      </div>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
      >
        <Input
          aria-label="Message"
          placeholder="Ask about your feed…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button type="submit">Send</Button>
      </form>
    </div>
  );
}
