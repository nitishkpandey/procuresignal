"use client";

import Link from "next/link";

import { PERSONAS } from "@/lib/personas";
import { useUserStore } from "@/store/user";

export function Header() {
  const userId = useUserStore((s) => s.userId);
  const setUserId = useUserStore((s) => s.setUserId);

  // Keep an unknown persisted id (e.g. a custom user) selectable.
  const options = PERSONAS.some((p) => p.id === userId)
    ? PERSONAS
    : [{ id: userId, label: userId }, ...PERSONAS];

  return (
    <header className="mb-6 flex flex-col gap-3 border-b border-slate-200 pb-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-4">
        <Link href="/" className="text-lg font-semibold">
          ProcureSignal
        </Link>
        <nav className="flex gap-3 text-sm text-slate-600">
          <Link href="/">Feed</Link>
          <Link href="/preferences">Preferences</Link>
          <Link href="/chat">Chat</Link>
        </nav>
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <span>Viewing as</span>
        <select
          aria-label="Viewing as"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm"
        >
          {options.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
    </header>
  );
}
