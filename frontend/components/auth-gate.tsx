"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { login, register } from "@/lib/auth";
import { t } from "@/lib/i18n";
import { useUserStore } from "@/store/user";

const MINIMUM_PASSWORD_LENGTH = 12;

type Mode = "login" | "register";

function messageFor(error: unknown, mode: Mode): string {
  const status =
    typeof error === "object" && error && "response" in error
      ? (error as { response?: { status?: number } }).response?.status
      : undefined;

  if (status === 409) return "That email already has an account. Sign in instead.";
  if (status === 401) return "Email or password is incorrect.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status === 422) return `Password must be at least ${MINIMUM_PASSWORD_LENGTH} characters.`;
  return mode === "login" ? "Could not sign in." : "Could not create the account.";
}

export function AuthGate() {
  const setUser = useUserStore((s) => s.setUser);
  const language = useUserStore((s) => s.platformLanguage);

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const address = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      setError(t(language, "app.invalidEmail"));
      return;
    }
    if (mode === "register" && password.length < MINIMUM_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MINIMUM_PASSWORD_LENGTH} characters.`);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const user =
        mode === "login"
          ? await login(address, password)
          : await register(address, password, fullName.trim());
      setUser(user);
    } catch (err) {
      setError(messageFor(err, mode));
    } finally {
      setBusy(false);
    }
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
            <p className="text-sm text-slate-500">
              {mode === "login" ? t(language, "app.signInTitle") : "Create your account"}
            </p>
          </div>
        </div>

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {mode === "register" ? (
            <Input
              aria-label="Full name"
              autoComplete="name"
              placeholder="Full name (optional)"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          ) : null}

          <Input
            aria-label={t(language, "app.companyEmail")}
            autoComplete="email"
            inputMode="email"
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            aria-label="Password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error ? (
            <p className="text-sm text-red-700" role="alert">
              {error}
            </p>
          ) : null}

          <Button className="w-full" type="submit" disabled={busy}>
            {busy ? "Working…" : mode === "login" ? t(language, "app.continue") : "Create account"}
          </Button>
        </form>

        <button
          className="mt-4 w-full text-sm text-slate-600 underline underline-offset-2"
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
        </button>
      </section>
    </main>
  );
}
