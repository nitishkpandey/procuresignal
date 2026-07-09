"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useUserStore } from "@/store/user";

const NAV = [
  { href: "/", label: "Feed" },
  { href: "/preferences", label: "Preferences" },
  { href: "/chat", label: "Chat" },
];

export function Header() {
  const pathname = usePathname() ?? "/";
  const userId = useUserStore((s) => s.userId);
  const clearUser = useUserStore((s) => s.clearUser);

  return (
    <header className="mb-6 border-b border-slate-200 pb-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Link href="/" className="flex items-center gap-2 text-lg font-semibold text-slate-950">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-950 text-xs font-semibold text-white">
              PS
            </span>
            ProcureSignal
          </Link>
          <nav className="flex flex-wrap gap-1 rounded-md bg-slate-100 p-1 text-sm text-slate-600">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded px-3 py-1.5 transition ${
                    active
                      ? "bg-white text-slate-950 shadow-sm"
                      : "hover:bg-white/70 hover:text-slate-950"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm text-slate-600 sm:justify-start">
          <span className="max-w-[220px] truncate font-medium text-slate-800">{userId}</span>
          <button
            type="button"
            onClick={clearUser}
            className="rounded px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-white hover:text-slate-950"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
