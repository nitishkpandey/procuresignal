"use client";

import { useState, type ReactNode } from "react";

import { Header } from "@/components/header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { t } from "@/lib/i18n";
import { useUserStore } from "@/store/user";

export function AppShell({ children }: { children: ReactNode }) {
  const userId = useUserStore((s) => s.userId);

  if (!userId) return <CompanyEmailGate />;

  return (
    <div className="mx-auto min-h-screen max-w-7xl px-4 py-5 sm:px-6 lg:px-8">
      <Header />
      {children}
    </div>
  );
}

function CompanyEmailGate() {
  const setUserId = useUserStore((s) => s.setUserId);
  const language = useUserStore((s) => s.platformLanguage);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const value = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      setError(t(language, "app.invalidEmail"));
      return;
    }
    setError(null);
    setUserId(value);
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-8">
      <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 shadow-sm shadow-slate-300/70">
        <div className="mb-5 flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-950 text-sm font-semibold text-white">
            PS
          </span>
          <div>
            <h1 className="text-lg font-semibold text-slate-950">ProcureSignal</h1>
            <p className="text-sm text-slate-500">{t(language, "app.signInTitle")}</p>
          </div>
        </div>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Input
            aria-label={t(language, "app.companyEmail")}
            autoComplete="email"
            inputMode="email"
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {error ? <p className="text-sm text-red-700">{error}</p> : null}
          <Button className="w-full" type="submit">
            {t(language, "app.continue")}
          </Button>
        </form>
      </section>
    </main>
  );
}
