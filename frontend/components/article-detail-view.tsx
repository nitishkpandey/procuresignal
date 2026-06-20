"use client";

import Link from "next/link";

import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { SignalBadge } from "@/components/signal-badge";
import { getArticle } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export function ArticleDetailView({ id }: { id: number }) {
  const { data, loading, error } = useApi(() => getArticle(id), [id]);

  if (loading) return <Spinner label="Loading article…" />;
  if (error) return <EmptyState title="Article not found" hint={error} />;
  if (!data) return <EmptyState title="Article not found" />;

  return (
    <article className="space-y-4">
      <Link href="/" className="text-sm underline">
        ← Back to feed
      </Link>
      <Card>
        <div className="text-xs uppercase tracking-wide text-slate-500">
          {data.category} · {data.source_name}
        </div>
        <h1 className="mt-1 text-xl font-semibold">{data.title}</h1>
        <div className="mt-2 flex flex-wrap gap-1">
          {data.signal_tags.map((t) => (
            <SignalBadge key={t} signal={t} priority={t === data.priority_signal} />
          ))}
        </div>
        <p className="mt-3 text-slate-700">{data.summary}</p>
        {data.description ? <p className="mt-3 text-sm text-slate-600">{data.description}</p> : null}
        <dl className="mt-4 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <Detail label="Suppliers" items={data.detected_suppliers} />
          <Detail label="Regions" items={data.detected_regions} />
          <Detail label="Categories" items={data.detected_categories} />
        </dl>
        <a
          href={data.article_url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-block text-sm font-medium underline"
        >
          Read original article →
        </a>
      </Card>
    </article>
  );
}

function Detail({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <dt className="font-medium text-slate-500">{label}</dt>
      <dd className="text-slate-800">{items.length ? items.join(", ") : "—"}</dd>
    </div>
  );
}
