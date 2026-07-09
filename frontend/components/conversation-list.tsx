"use client";

import { Button } from "@/components/ui/button";
import type { Conversation } from "@/lib/types";

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onClearHistory,
  clearing,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onClearHistory: () => void;
  clearing?: boolean;
}) {
  return (
    <aside className="w-full shrink-0 rounded-lg border border-slate-200 bg-white p-3 shadow-sm shadow-slate-200/70 lg:w-72">
      <Button className="mb-4 w-full whitespace-nowrap" onClick={onNew}>
        New conversation
      </Button>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase text-slate-500">Recent chats</p>
        <button
          type="button"
          onClick={onClearHistory}
          disabled={conversations.length === 0 || clearing}
          className="rounded px-1.5 py-1 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {clearing ? "Clearing..." : "Clear history"}
        </button>
      </div>
      <ul className="max-h-[58vh] space-y-1 overflow-y-auto pr-1">
        {conversations.slice(0, 12).map((c) => (
          <li key={c.conversation_id}>
            <button
              onClick={() => onSelect(c.conversation_id)}
              className={`w-full rounded-md border px-2.5 py-2 text-left text-sm transition ${
                c.conversation_id === activeId
                  ? "border-slate-300 bg-slate-100 text-slate-950"
                  : "border-transparent text-slate-600 hover:border-slate-200 hover:bg-slate-50 hover:text-slate-950"
              }`}
            >
              <span className="block truncate font-medium">{c.title || "Untitled conversation"}</span>
              <span className="mt-0.5 block text-xs text-slate-400">
                {c.message_count || 0} message{c.message_count === 1 ? "" : "s"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {conversations.length === 0 ? (
        <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-500">
          No chats yet.
        </p>
      ) : null}
    </aside>
  );
}
