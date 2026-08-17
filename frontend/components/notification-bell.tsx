"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { getNotifications, markNotificationRead } from "@/lib/api";
import { formatDate, humanize } from "@/lib/labels";
import type { NotificationItem } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const SEVERITY_TONE: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-slate-100 text-slate-700",
};

function AlertRow({ item, onRead }: { item: NotificationItem; onRead: () => void }) {
  return (
    <li className="space-y-1 px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <p
          className={`text-sm ${item.read_at ? "text-slate-600" : "font-medium text-slate-950"}`}
        >
          {item.subject}
        </p>
        {item.read_at ? null : (
          <button
            type="button"
            aria-label={`Mark read: ${item.subject}`}
            onClick={onRead}
            className="shrink-0 text-xs font-medium text-slate-500 underline underline-offset-2 hover:text-slate-900"
          >
            Mark read
          </button>
        )}
      </div>
      <p className="text-xs text-slate-600">{item.body}</p>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {item.severity ? (
          <Badge className={SEVERITY_TONE[item.severity] ?? SEVERITY_TONE.low}>
            {humanize(item.severity)}
          </Badge>
        ) : null}
        {/* Why this arrived, not just that it did. */}
        {item.rule_name ? <span>via {item.rule_name}</span> : null}
        {item.delivered_at ? <span>{formatDate(item.delivered_at)}</span> : null}
      </div>
    </li>
  );
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const feed = useApi(() => getNotifications(), "notifications");
  const items = useMemo(() => feed.data?.items ?? [], [feed.data?.items]);
  const unread = feed.data?.unread_count ?? 0;

  const read = async (publicId: string) => {
    try {
      await markNotificationRead(publicId);
      feed.reload();
    } catch {
      // Leaving it unread is the safe failure: the alert stays visible rather than
      // disappearing from a feed the server still considers unread.
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={unread > 0 ? `${unread} unread notifications` : "Notifications"}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded px-2 py-1 text-sm text-slate-600 transition hover:bg-white hover:text-slate-950"
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 ? (
          <Badge className="bg-red-600 text-white">{unread > 99 ? "99+" : unread}</Badge>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 z-20 mt-2 w-80 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          {items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-slate-500">Nothing new right now.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-slate-200 overflow-y-auto">
              {items.map((item) => (
                <AlertRow key={item.public_id} item={item} onRead={() => void read(item.public_id)} />
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
