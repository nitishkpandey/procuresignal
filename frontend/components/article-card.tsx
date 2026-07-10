"use client";

import Link from "next/link";

import { SignalBadge } from "@/components/signal-badge";
import { t } from "@/lib/i18n";
import { formatDate, humanize, scoreTier } from "@/lib/labels";
import type { FeedArticle } from "@/lib/types";
import { useUserStore } from "@/store/user";

export function ArticleCard({
  article,
  read = false,
  onOpen,
}: {
  article: FeedArticle;
  read?: boolean;
  onOpen?: (id: number) => void;
}) {
  const language = useUserStore((s) => s.platformLanguage);
  const tier = scoreTier(article.relevance_score);
  const pct = Math.round(article.relevance_score * 100);
  const suppliers = article.detected_suppliers ?? [];
  const regions = article.detected_regions ?? [];

  return (
    <article className={`transition ${read ? "opacity-60" : ""}`}>
      <Link
        href={`/articles/${article.id}`}
        className="block px-4 py-4 hover:bg-slate-50 sm:px-5"
        onClick={() => onOpen?.(article.id)}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span className="font-semibold uppercase text-slate-600">
              {humanize(article.category)}
            </span>
            <span aria-hidden>|</span>
            <span>{article.source_name}</span>
            <span aria-hidden>|</span>
            <span>{formatDate(article.published_at)}</span>
          </div>
          <span
            className={`shrink-0 text-xs font-semibold ${tier.tone}`}
            title={t(language, "article.matchTitle", { pct })}
          >
            {pct}%
          </span>
        </div>

        <h3 className="mt-2 text-base font-semibold leading-snug text-slate-950">{article.title}</h3>
        <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{article.summary}</p>

        {(article.priority_signal || suppliers.length > 0 || regions.length > 0) && (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            {article.priority_signal && (
              <span className="font-medium text-red-700">
                {t(language, "article.priority")}:{" "}
                {humanize(article.priority_signal)}
              </span>
            )}
            {suppliers.length > 0 && (
              <span className="max-w-full">
                {t(language, "article.suppliers")}: {suppliers.map(humanize).join(", ")}
              </span>
            )}
            {regions.length > 0 && (
              <span className="max-w-full">
                {t(language, "article.regions")}: {regions.map(humanize).join(", ")}
              </span>
            )}
          </div>
        )}

        {article.signal_tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {article.signal_tags.map((tag) => (
              <SignalBadge key={tag} signal={tag} priority={tag === article.priority_signal} />
            ))}
          </div>
        )}
      </Link>
    </article>
  );
}
