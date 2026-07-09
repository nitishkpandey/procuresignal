"use client";

import { useMemo } from "react";

import { Spinner } from "@/components/ui/spinner";
import { getCurrencyMonitor } from "@/lib/api";
import type { CurrencySignal } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export function CurrencyView() {
  return (
    <main className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <section className="border-b border-slate-200 pb-5 lg:border-b-0 lg:pb-0">
        <p className="text-xs font-semibold uppercase text-slate-500">Procurement timing</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">Currency timing</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
          A focused EUR monitor for procurement teams timing supplier payments and bulk buys.
        </p>
      </section>
      <CurrencyRail />
    </main>
  );
}

export function CurrencyRail({ className = "" }: { className?: string }) {
  const { data, loading, error } = useApi(() => getCurrencyMonitor({ days: 30 }), []);
  const currencies = useMemo(() => data?.currencies ?? [], [data?.currencies]);
  const strongest = useMemo(() => pickStrongest(currencies), [currencies]);

  return (
    <aside
      className={`overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70 ${className}`}
      aria-label="EUR currency monitor"
    >
      <div className="border-b border-slate-100 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase text-slate-500">Currency timing</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">EUR monitor</h2>
          </div>
          <span className="rounded-md bg-slate-950 px-2 py-1 text-xs font-semibold text-white">
            EUR
          </span>
        </div>
        {data ? (
          <p className="mt-2 text-xs leading-5 text-slate-500">
            {data.lookback_days}-day range, refreshed from market rates as of {data.as_of}.
          </p>
        ) : null}
      </div>

      {loading ? <Spinner label="Loading EUR timing..." /> : null}
      {error ? (
        <RailNotice title="Currency monitor unavailable" hint={error} />
      ) : null}
      {!loading && !error && !data ? (
        <RailNotice title="Currency monitor unavailable" />
      ) : null}
      {!loading && !error && data ? (
        <div>
          {strongest ? (
            <div className="border-b border-slate-100 px-4 py-3">
              <p className="text-xs font-semibold uppercase text-slate-500">Best current window</p>
              <p className="mt-1 text-sm font-semibold text-slate-950">
                EUR / {strongest.currency} at {Math.round(strongest.range_position * 100)}% of range
              </p>
            </div>
          ) : null}
          <div className="divide-y divide-slate-100">
            {currencies.map((item) => (
              <CurrencyRow key={item.currency} item={item} />
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}

function RailNotice({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-4">
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {hint ? <p className="mt-1 text-xs leading-5 text-slate-500">{hint}</p> : null}
    </div>
  );
}

function CurrencyRow({ item }: { item: CurrencySignal }) {
  const position = Math.round(item.range_position * 100);
  const timing = timingSignal(item.range_position);

  return (
    <article className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">EUR / {item.currency}</p>
          <p className="mt-0.5 text-base font-semibold text-slate-950">
            {item.latest_rate.toFixed(4)}
          </p>
        </div>
        <span className={`rounded px-2 py-1 text-xs font-semibold ${timing.className}`}>
          {timing.label}
        </span>
      </div>
      <div className="mt-3 h-1.5 rounded-full bg-slate-100">
        <div
          className={`h-1.5 rounded-full ${timing.barClassName}`}
          style={{ width: `${position}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>
          Low {item.range_low.toFixed(4)} / High {item.range_high.toFixed(4)}
        </span>
        <span className="font-medium text-slate-600">{position}%</span>
      </div>
    </article>
  );
}

function timingSignal(position: number) {
  if (position >= 0.75) {
    return {
      label: "Buy window",
      className: "bg-emerald-50 text-emerald-700",
      barClassName: "bg-emerald-600",
    };
  }
  if (position <= 0.25) {
    return {
      label: "Wait",
      className: "bg-amber-50 text-amber-700",
      barClassName: "bg-amber-500",
    };
  }
  return {
    label: "Neutral",
    className: "bg-slate-100 text-slate-700",
    barClassName: "bg-slate-600",
  };
}

function pickStrongest(currencies: CurrencySignal[]) {
  return currencies.reduce<CurrencySignal | null>(
    (best, item) => (!best || item.range_position > best.range_position ? item : best),
    null,
  );
}
