"use client";

import { useMemo } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { getCurrencyMonitor } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export function CurrencyView() {
  const { data, loading, error } = useApi(() => getCurrencyMonitor({ days: 30 }), []);
  const currencies = useMemo(() => data?.currencies ?? [], [data?.currencies]);

  if (loading) return <Spinner label="Loading currency monitor..." />;
  if (error) return <EmptyState title="Currency monitor unavailable" hint={error} />;
  if (!data) return <EmptyState title="Currency monitor unavailable" />;

  return (
    <main className="space-y-5">
      <section className="border-b border-slate-200 pb-5">
        <p className="text-xs font-semibold uppercase text-slate-500">Procurement timing</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">EUR currency monitor</h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
          EUR positioning against supplier-market currencies over the last {data.lookback_days} days.
        </p>
      </section>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
        <div className="divide-y divide-slate-100">
          {currencies.map((item) => (
            <article key={item.currency} className="px-4 py-4 sm:px-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase text-slate-500">
                    EUR / {item.currency}
                  </p>
                  <h2 className="mt-1 text-lg font-semibold text-slate-950">
                    {item.latest_rate.toFixed(4)}
                  </h2>
                </div>
                <span className="text-sm font-medium text-slate-600">
                  {Math.round(item.range_position * 100)}% of range
                </span>
              </div>
              <div className="mt-3 h-2 rounded-full bg-slate-100">
                <div
                  className="h-2 rounded-full bg-slate-950"
                  style={{ width: `${Math.round(item.range_position * 100)}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Low {item.range_low.toFixed(4)} · High {item.range_high.toFixed(4)} · As of{" "}
                {data.as_of}
              </p>
              <p className="mt-3 text-sm leading-6 text-slate-700">{item.procurement_signal}</p>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}
