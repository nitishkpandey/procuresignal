"use client";

import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ChatWindow } from "@/components/chat-window";
import { ConversationList } from "@/components/conversation-list";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { clearConversationHistory, createConversation, listConversations } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import { useUserStore } from "@/store/user";

export function ChatView() {
  const userId = useUserStore((s) => s.userId);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    listConversations(userId)
      .then((res) => {
        if (!active) return;
        setConversations(res.conversations);
        setActiveId(res.conversations[0]?.conversation_id ?? null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Unable to load conversations.");
        setConversations([]);
        setActiveId(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [userId]);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listConversations(userId);
      setConversations(res.conversations);
      setActiveId(res.conversations[0]?.conversation_id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load conversations.");
      setConversations([]);
      setActiveId(null);
    } finally {
      setLoading(false);
    }
  };

  const onNew = async () => {
    setError(null);
    try {
      const conv = await createConversation(userId);
      setConversations((prev) => [conv, ...prev]);
      setActiveId(conv.conversation_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create a conversation.");
    }
  };

  const onClearHistory = async () => {
    if (conversations.length === 0 || clearing) return;
    if (!window.confirm("Clear all chat history for this email?")) return;

    setClearing(true);
    setError(null);
    try {
      await clearConversationHistory(userId);
      setConversations([]);
      setActiveId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to clear chat history.");
    } finally {
      setClearing(false);
    }
  };

  return (
    <main className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={onNew}
        onClearHistory={onClearHistory}
        clearing={clearing}
      />
      <div className="min-w-0 flex-1">
        {activeId ? (
          <div className="space-y-3">
            {error ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <ChatWindow key={activeId} userId={userId} conversationId={activeId} />
          </div>
        ) : loading ? (
          <AssistantShell>
            <Spinner label="Loading conversations..." />
          </AssistantShell>
        ) : error ? (
          <AssistantShell>
            <div className="rounded-lg border border-red-200 bg-red-50/70 p-4">
              <p className="text-sm font-semibold text-red-800">Conversations unavailable</p>
              <p className="mt-1 text-sm text-red-700">
                The assistant service did not respond. Retry when the API is available.
              </p>
              <Button className="mt-3" variant="secondary" onClick={reload}>
                Retry
              </Button>
            </div>
          </AssistantShell>
        ) : (
          <AssistantShell>
            <EmptyState
              title="No conversation selected"
              hint="Start a new conversation to ask questions grounded in the current feed."
            />
          </AssistantShell>
        )}
      </div>
    </main>
  );
}

function AssistantShell({ children }: { children: ReactNode }) {
  return (
    <section className="flex min-h-[70vh] flex-col rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
      <div className="border-b border-slate-200 px-4 py-3">
        <h1 className="text-base font-semibold text-slate-950">Procurement assistant</h1>
        <p className="mt-1 text-sm text-slate-500">
          Ask focused questions about suppliers, risks, regions, and recent signals.
        </p>
      </div>
      <div className="flex flex-1 items-center justify-center p-4">{children}</div>
    </section>
  );
}
