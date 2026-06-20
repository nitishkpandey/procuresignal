"use client";

import { useState } from "react";

import Link from "next/link";

import { Input } from "@/components/ui/input";
import { useUserStore } from "@/store/user";

export function Header() {
  const userId = useUserStore((s) => s.userId);
  const setUserId = useUserStore((s) => s.setUserId);
  const [draft, setDraft] = useState(userId);

  const onChange = (value: string) => {
    setDraft(value);
    setUserId(value);
  };

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
        <span>User ID</span>
        <Input
          aria-label="User ID"
          value={draft}
          onChange={(e) => onChange(e.target.value)}
          className="w-40"
        />
      </label>
    </header>
  );
}
