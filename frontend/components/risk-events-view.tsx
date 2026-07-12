"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { getRiskEvents, updateRiskEventStatus } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatDate, humanize } from "@/lib/labels";
import type { RiskEvent, RiskEventStatus } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useUserStore } from "@/store/user";

export function RiskEventsView() {
  const userId = useUserStore((s) => s.userId);
  const language = useUserStore((s) => s.platformLanguage);
  const risks = useApi(() => getRiskEvents(userId, { language, limit: 50 }), [userId, language]);
  const events = useMemo(() => risks.data?.events ?? [], [risks.data?.events]);
  const totalCount = risks.data?.total_count ?? events.length;

  return (
    <main className="space-y-5">
      <section className="flex flex-col gap-4 border-b border-slate-200 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">
            {t(language, "risks.eyebrow")}
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">
            {t(language, "risks.title")}
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
            {t(language, "risks.subtitle")}
          </p>
        </div>
        {totalCount > 0 ? (
          <span className="text-sm font-medium text-slate-600">
            {t(language, totalCount === 1 ? "risks.countOne" : "risks.countMany", {
              count: totalCount,
            })}
          </span>
        ) : null}
      </section>

      <RiskEventList
        loading={risks.loading}
        error={risks.error}
        events={events}
        onRetry={risks.reload}
        language={language}
      />
    </main>
  );
}

function RiskEventList({
  loading,
  error,
  events,
  onRetry,
  language,
}: {
  loading: boolean;
  error: string | null;
  events: RiskEvent[];
  onRetry: () => void;
  language: string;
}) {
  if (loading) return <Spinner label={t(language, "risks.loading")} />;
  if (error) {
    return (
      <Card className="border-red-200 bg-red-50/70">
        <p className="text-sm font-semibold text-red-800">{t(language, "risks.unavailableTitle")}</p>
        <p className="mt-1 text-sm text-red-700">{t(language, "risks.unavailableHint")}</p>
        <Button className="mt-3" variant="secondary" onClick={onRetry}>
          {t(language, "common.retry")}
        </Button>
      </Card>
    );
  }
  if (events.length === 0) {
    return <EmptyState title={t(language, "risks.noEventsTitle")} hint={t(language, "risks.noEventsHint")} />;
  }
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
      <div className="divide-y divide-slate-100">
        {events.map((event) => (
          <RiskEventRow key={event.id} event={event} language={language} />
        ))}
      </div>
    </div>
  );
}

function RiskEventRow({ event, language }: { event: RiskEvent; language: string }) {
  const [status, setStatus] = useState<RiskEventStatus>(event.status);
  const [updating, setUpdating] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const confidence = Math.round(event.confidence * 100);

  const changeStatus = async (nextStatus: RiskEventStatus) => {
    const previousStatus = status;
    setStatusError(null);
    setStatus(nextStatus);
    setUpdating(true);
    try {
      await updateRiskEventStatus(event.id, nextStatus);
    } catch {
      setStatus(previousStatus);
      setStatusError(t(language, "risks.statusUpdateFailed"));
    } finally {
      setUpdating(false);
    }
  };

  return (
    <article className="px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span className="font-semibold uppercase text-slate-600">{humanize(event.risk_type)}</span>
            <span aria-hidden>|</span>
            <span>{humanize(event.severity)}</span>
            <span aria-hidden>|</span>
            {event.source_url ? (
              <a
                href={event.source_url}
                target="_blank"
                rel="noreferrer"
                className="underline decoration-slate-300 underline-offset-2 hover:text-slate-900"
              >
                {event.source_name}
              </a>
            ) : (
              <span>{event.source_name}</span>
            )}
            <span aria-hidden>|</span>
            <span>{formatDate(event.published_at)}</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-700">{event.evidence_snippet}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-sm font-semibold text-slate-950">{confidence}%</span>
          <div>
            <select
              aria-label={`Status for risk event ${event.id}`}
              value={status}
              onChange={(e) => void changeStatus(e.target.value as RiskEventStatus)}
              disabled={updating}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700 shadow-sm"
            >
              <option value="new">{t(language, "risks.new")}</option>
              <option value="reviewed">{t(language, "risks.reviewed")}</option>
              <option value="dismissed">{t(language, "risks.dismissed")}</option>
            </select>
            {statusError ? (
              <p role="alert" className="mt-1 max-w-40 text-xs text-red-700">
                {statusError}
              </p>
            ) : null}
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {event.affected_suppliers.length > 0 ? (
          <span>{t(language, "article.suppliers")}: {event.affected_suppliers.map(humanize).join(", ")}</span>
        ) : null}
        {event.affected_locations.length > 0 ? (
          <span>{t(language, "article.regions")}: {event.affected_locations.map(humanize).join(", ")}</span>
        ) : null}
      </div>
      <p className="mt-3 text-xs font-semibold uppercase text-slate-500">
        {t(language, "risks.recommendation")}
      </p>
      <p className="mt-1 text-sm leading-6 text-slate-700">{event.recommendation}</p>
    </article>
  );
}
