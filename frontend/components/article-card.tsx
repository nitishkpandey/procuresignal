import Link from "next/link";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SignalBadge } from "@/components/signal-badge";
import { formatDate, humanize, scoreTier } from "@/lib/labels";
import type { FeedArticle } from "@/lib/types";

export function ArticleCard({
  article,
  read = false,
  onOpen,
}: {
  article: FeedArticle;
  read?: boolean;
  onOpen?: (id: number) => void;
}) {
  const tier = scoreTier(article.relevance_score);
  const pct = Math.round(article.relevance_score * 100);
  const suppliers = article.detected_suppliers ?? [];
  const regions = article.detected_regions ?? [];

  return (
    <Card className={`transition hover:border-slate-400 ${read ? "opacity-60" : ""}`}>
      <Link
        href={`/articles/${article.id}`}
        className="block"
        onClick={() => onOpen?.(article.id)}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span className="font-medium uppercase tracking-wide text-slate-600">
              {humanize(article.category)}
            </span>
            <span>·</span>
            <span>{article.source_name}</span>
            <span>·</span>
            <span>{formatDate(article.published_at)}</span>
          </div>
          <Badge className={`shrink-0 ${tier.tone}`} title={`Relevance ${pct}%`}>
            {tier.label} · {pct}%
          </Badge>
        </div>

        <h3 className="mt-1.5 font-semibold leading-snug text-slate-900">{article.title}</h3>
        <p className="mt-1 line-clamp-2 text-sm text-slate-600">{article.summary}</p>

        {(article.priority_signal || suppliers.length > 0 || regions.length > 0) && (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            {article.priority_signal && (
              <span className="inline-flex items-center gap-1 font-medium text-red-700">
                <span aria-hidden>▲</span>
                {humanize(article.priority_signal)}
              </span>
            )}
            {suppliers.length > 0 && (
              <span className="truncate">
                <span aria-hidden>🏢</span> {suppliers.map(humanize).join(", ")}
              </span>
            )}
            {regions.length > 0 && (
              <span className="truncate">
                <span aria-hidden>📍</span> {regions.map(humanize).join(", ")}
              </span>
            )}
          </div>
        )}

        {article.signal_tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {article.signal_tags.map((tag) => (
              <SignalBadge key={tag} signal={tag} priority={tag === article.priority_signal} />
            ))}
          </div>
        )}
      </Link>
    </Card>
  );
}
