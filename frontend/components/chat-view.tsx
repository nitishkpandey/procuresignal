"use client";

import { useEffect, useState } from "react";

import { ChatWindow } from "@/components/chat-window";
import { ConversationList } from "@/components/conversation-list";
import { EmptyState } from "@/components/ui/empty-state";
import { createConversation, listConversations } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import { useUserStore } from "@/store/user";

export function ChatView() {
  const userId = useUserStore((s) => s.userId);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listConversations(userId).then((res) => {
      if (!active) return;
      setConversations(res.conversations);
      setActiveId(res.conversations[0]?.conversation_id ?? null);
    });
    return () => {
      active = false;
    };
  }, [userId]);

  const onNew = async () => {
    const conv = await createConversation(userId);
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.conversation_id);
  };

  return (
    <main className="flex flex-col gap-4 sm:flex-row">
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={onNew}
      />
      <div className="flex-1">
        {activeId ? (
          <ChatWindow key={activeId} userId={userId} conversationId={activeId} />
        ) : (
          <EmptyState title="No conversation selected" hint="Start a new conversation." />
        )}
      </div>
    </main>
  );
}
