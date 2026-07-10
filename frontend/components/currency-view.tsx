"use client";

import { useMemo, useState } from "react";

import { Spinner } from "@/components/ui/spinner";
import { getCurrencyMonitor } from "@/lib/api";
import { t, type TranslationKey } from "@/lib/i18n";
import type { CurrencySignal } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useUserStore } from "@/store/user";

const COMPACT_PAIR_COUNT = 7;

export function CurrencyView() {
  const language = useUserStore((s) => s.platformLanguage);

  return (
    <main className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <section className="border-b border-slate-200 pb-5 lg:border-b-0 lg:pb-0">
        <p className="text-xs font-semibold uppercase text-slate-500">
          {t(language, "currency.procurementTiming")}
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          {t(language, "currency.timingTitle")}
        </h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
          {t(language, "currency.viewSubtitle")}
        </p>
      </section>
      <CurrencyRail />
    </main>
  );
}

export function CurrencyRail({ className = "" }: { className?: string }) {
  const language = useUserStore((s) => s.platformLanguage);
  const [expanded, setExpanded] = useState(false);
  const { data, loading, error } = useApi(() => getCurrencyMonitor({ days: 30 }), []);
  const currencies = useMemo(() => data?.currencies ?? [], [data?.currencies]);
  const sortedCurrencies = useMemo(() => sortBySignalStrength(currencies), [currencies]);
  const visibleCurrencies = expanded
    ? sortedCurrencies
    : sortedCurrencies.slice(0, COMPACT_PAIR_COUNT);
  const strongest = useMemo(() => pickStrongest(currencies), [currencies]);

  return (
    <aside
      className={`overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70 ${className}`}
      aria-label={t(language, "currency.railAria")}
    >
      <div className="border-b border-slate-100 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase text-slate-500">
              {t(language, "currency.timingTitle")}
            </p>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">EUR monitor</h2>
          </div>
          <span className="rounded-md bg-slate-950 px-2 py-1 text-xs font-semibold text-white">
            EUR
          </span>
        </div>
        {data ? (
          <p className="mt-2 text-xs leading-5 text-slate-500">
            {t(language, "currency.latest", {
              date: data.as_of,
              days: data.lookback_days,
            })}
          </p>
        ) : null}
        {currencies.length > 0 ? (
          <p className="mt-2 text-xs font-medium text-slate-600">
            {t(language, "currency.showingPairs", {
              shown: visibleCurrencies.length,
              total: currencies.length,
            })}
          </p>
        ) : null}
      </div>

      {loading ? <Spinner label={t(language, "currency.loading")} /> : null}
      {error ? (
        <RailNotice title={t(language, "currency.unavailable")} hint={error} />
      ) : null}
      {!loading && !error && !data ? (
        <RailNotice title={t(language, "currency.unavailable")} />
      ) : null}
      {!loading && !error && data ? (
        <div>
          {strongest ? (
            <div className="border-b border-slate-100 px-4 py-3">
              <p className="text-xs font-semibold uppercase text-slate-500">
                {t(language, "currency.bestWindow")}
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-950">
                {t(language, "currency.bestWindowValue", {
                  currency: strongest.currency,
                  position: Math.round(strongest.range_position * 100),
                })}
              </p>
            </div>
          ) : null}
          <div className="divide-y divide-slate-100">
            {visibleCurrencies.map((item) => (
              <CurrencyRow key={item.currency} item={item} language={language} />
            ))}
          </div>
          {currencies.length > COMPACT_PAIR_COUNT ? (
            <div className="border-t border-slate-100 px-4 py-3">
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-white hover:text-slate-950"
              >
                {expanded ? t(language, "currency.showFewer") : t(language, "currency.showAllPairs")}
              </button>
            </div>
          ) : null}
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

function CurrencyRow({ item, language }: { item: CurrencySignal; language: string }) {
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
          {t(language, timing.labelKey)}
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
          {t(language, "currency.lowHigh", {
            low: item.range_low.toFixed(4),
            high: item.range_high.toFixed(4),
          })}
        </span>
        <span className="font-medium text-slate-600">{position}%</span>
      </div>
    </article>
  );
}

function timingSignal(position: number) {
  if (position >= 0.75) {
    return {
      labelKey: "currency.buyWindow" as TranslationKey,
      className: "bg-emerald-50 text-emerald-700",
      barClassName: "bg-emerald-600",
    };
  }
  if (position <= 0.25) {
    return {
      labelKey: "currency.wait" as TranslationKey,
      className: "bg-amber-50 text-amber-700",
      barClassName: "bg-amber-500",
    };
  }
  return {
    labelKey: "currency.neutral" as TranslationKey,
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

function sortBySignalStrength(currencies: CurrencySignal[]) {
  return [...currencies].sort((a, b) => {
    const signalDelta =
      Math.abs(b.range_position - 0.5) - Math.abs(a.range_position - 0.5);
    if (signalDelta !== 0) return signalDelta;
    return a.currency.localeCompare(b.currency);
  });
}
