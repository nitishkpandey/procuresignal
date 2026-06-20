"use client";

import { Button } from "@/components/ui/button";
import type { Conversation } from "@/lib/types";

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="w-full sm:w-56">
      <Button className="mb-3 w-full" onClick={onNew}>
        New conversation
      </Button>
      <ul className="space-y-1">
        {conversations.map((c) => (
          <li key={c.conversation_id}>
            <button
              onClick={() => onSelect(c.conversation_id)}
              className={`w-full truncate rounded-md px-2 py-1 text-left text-sm ${
                c.conversation_id === activeId ? "bg-slate-200" : "hover:bg-slate-100"
              }`}
            >
              {c.title || "Untitled conversation"}
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
