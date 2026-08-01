"use client";

import { useEffect, useState, type ReactNode } from "react";

import { AuthGate } from "@/components/auth-gate";
import { Header } from "@/components/header";
import { Spinner } from "@/components/ui/spinner";
import { restoreSession } from "@/lib/auth";
import { useUserStore } from "@/store/user";

export function AppShell({ children }: { children: ReactNode }) {
  const user = useUserStore((s) => s.user);
  const setUser = useUserStore((s) => s.setUser);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    let active = true;

    // The access token does not survive a reload, so a returning visitor is recovered
    // from the refresh cookie rather than being asked to sign in again.
    restoreSession()
      .then((restored) => {
        if (active && restored) setUser(restored);
      })
      // Restore already swallows its own failures, but an unexpected rejection here
      // would strand the user on the spinner forever.
      .catch(() => null)
      .finally(() => {
        if (active) setRestoring(false);
      });

    return () => {
      active = false;
    };
  }, [setUser]);

  if (restoring) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100">
        <Spinner />
      </main>
    );
  }

  if (!user) return <AuthGate />;

  return (
    <div className="mx-auto min-h-screen max-w-7xl px-4 py-5 sm:px-6 lg:px-8">
      <Header />
      {children}
    </div>
  );
}
