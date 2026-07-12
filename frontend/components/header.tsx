"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { updatePlatformLanguage } from "@/lib/api";
import { LANGUAGE_OPTIONS, t, type TranslationKey } from "@/lib/i18n";
import { useUserStore } from "@/store/user";

const NAV = [
  { href: "/", labelKey: "nav.feed" },
  { href: "/risk-events", labelKey: "nav.risks" },
  { href: "/preferences", labelKey: "nav.preferences" },
  { href: "/chat", labelKey: "nav.chat" },
] satisfies { href: string; labelKey: TranslationKey }[];

export function Header() {
  const pathname = usePathname() ?? "/";
  const userId = useUserStore((s) => s.userId);
  const language = useUserStore((s) => s.platformLanguage);
  const setPlatformLanguage = useUserStore((s) => s.setPlatformLanguage);
  const clearUser = useUserStore((s) => s.clearUser);
  const [savingLanguage, setSavingLanguage] = useState(false);

  const onLanguageChange = async (nextLanguage: string) => {
    setPlatformLanguage(nextLanguage);
    if (!userId) return;
    setSavingLanguage(true);
    try {
      await updatePlatformLanguage(userId, nextLanguage);
    } catch {
      // Keep the local language responsive; the next full preference load can reconcile persistence.
    } finally {
      setSavingLanguage(false);
    }
  };

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
                  {t(language, item.labelKey)}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm text-slate-600 sm:justify-start">
          <select
            aria-label={t(language, "preferences.language")}
            value={language}
            disabled={savingLanguage}
            onChange={(e) => void onLanguageChange(e.target.value)}
            className="rounded border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700 shadow-sm transition focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-60"
          >
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.code} value={option.code}>
                {option.code.toUpperCase()}
              </option>
            ))}
          </select>
          <span className="max-w-[220px] truncate font-medium text-slate-800">{userId}</span>
          <button
            type="button"
            onClick={clearUser}
            className="rounded px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-white hover:text-slate-950"
          >
            {t(language, "nav.signOut")}
          </button>
        </div>
      </div>
    </header>
  );
}
