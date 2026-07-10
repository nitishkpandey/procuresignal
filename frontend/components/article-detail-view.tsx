"use client";

import Link from "next/link";

import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { SignalBadge } from "@/components/signal-badge";
import { getArticle } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatDate, humanize } from "@/lib/labels";
import { useApi } from "@/lib/useApi";
import { useUserStore } from "@/store/user";

export function ArticleDetailView({ id }: { id: number }) {
  const language = useUserStore((s) => s.platformLanguage);
  const { data, loading, error } = useApi(
    () => getArticle(id, { language }),
    [id, language],
  );

  if (loading) return <Spinner label={t(language, "article.loading")} />;
  if (error) return <EmptyState title={t(language, "article.notFound")} hint={error} />;
  if (!data) return <EmptyState title={t(language, "article.notFound")} />;

  return (
    <article className="space-y-4">
      <Link href="/" className="text-sm font-medium text-slate-600 hover:text-slate-950">
        {t(language, "search.backToFeed")}
      </Link>
      <Card className="p-5">
        <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium uppercase text-slate-500">
              <span>{humanize(data.category)}</span>
              <span aria-hidden>|</span>
              <span>{data.source_name}</span>
              <span aria-hidden>|</span>
              <span>{formatDate(data.published_at)}</span>
            </div>
            <h1 className="mt-2 max-w-4xl text-2xl font-semibold leading-tight text-slate-950">
              {data.title}
            </h1>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-1">
          {data.signal_tags.map((t) => (
            <SignalBadge key={t} signal={t} priority={t === data.priority_signal} />
          ))}
        </div>
        <p className="mt-4 text-base leading-7 text-slate-800">{data.summary}</p>
        {data.description ? (
          <p className="mt-3 text-sm leading-6 text-slate-600">{data.description}</p>
        ) : null}
        <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <Detail label={t(language, "article.suppliers")} items={data.detected_suppliers} language={language} />
          <Detail label={t(language, "article.regions")} items={data.detected_regions} language={language} />
          <Detail label={t(language, "preferences.categories")} items={data.detected_categories} language={language} />
        </dl>
        <a
          href={data.article_url}
          target="_blank"
          rel="noreferrer"
          className="mt-5 inline-flex rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
        >
          {t(language, "article.readOriginal")}
        </a>
      </Card>
    </article>
  );
}

function Detail({ label, items, language }: { label: string; items: string[]; language: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <dt className="text-xs font-semibold uppercase text-slate-500">{label}</dt>
      <dd className="mt-1 text-slate-800">
        {items.length ? items.map(humanize).join(", ") : t(language, "article.notDetected")}
      </dd>
    </div>
  );
}
