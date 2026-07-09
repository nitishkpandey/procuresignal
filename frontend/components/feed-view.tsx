"use client";

import { useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { CurrencyRail } from "@/components/currency-view";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getFeed, search } from "@/lib/api";
import { t } from "@/lib/i18n";
import { humanize } from "@/lib/labels";
import { useApi } from "@/lib/useApi";
import type { FeedArticle, SearchResult } from "@/lib/types";
import { useUserStore } from "@/store/user";
import { useReadStore } from "@/store/read";
import Link from "next/link";

type SortKey = "relevance" | "newest";

export function FeedView() {
  const userId = useUserStore((s) => s.userId);
  const language = useUserStore((s) => s.platformLanguage);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("relevance");
  const [category, setCategory] = useState<string | null>(null);

  const feed = useApi(() => getFeed(userId), [userId]);
  const results = useApi(
    () => (query ? search(query) : Promise.resolve(null)),
    [query],
  );

  const articles = useMemo(() => feed.data?.articles ?? [], [feed.data?.articles]);
  const categories = useMemo(
    () => Array.from(new Set(articles.map((a) => a.category))).sort(),
    [articles],
  );
  const visible = useMemo(() => {
    const list = category ? articles.filter((a) => a.category === category) : [...articles];
    list.sort((a, b) =>
      sort === "newest"
        ? new Date(b.published_at).getTime() - new Date(a.published_at).getTime()
        : b.relevance_score - a.relevance_score,
    );
    return list;
  }, [articles, category, sort]);

  return (
    <main className="space-y-5">
      <section className="flex flex-col gap-4 border-b border-slate-200 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">
            {t(language, "feed.eyebrow")}
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-normal text-slate-950">
            {t(language, "feed.title")}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            {t(language, "feed.subtitle")}
          </p>
        </div>
        <form
          className="w-full md:max-w-sm"
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(draft.trim());
          }}
        >
          <Input
            aria-label={t(language, "feed.searchAria")}
            placeholder={t(language, "feed.searchPlaceholder")}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </form>
      </section>

      {query ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <SearchResults
            loading={results.loading}
            error={results.error}
            items={results.data?.results ?? []}
            onClear={() => {
              setQuery("");
              setDraft("");
            }}
            onRetry={results.reload}
            language={language}
          />
          <CurrencyRail className="order-first xl:order-none xl:sticky xl:top-5 xl:self-start" />
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="space-y-5">
            {!feed.loading && !feed.error && articles.length > 0 && (
              <Toolbar
                count={visible.length}
                sort={sort}
                onSort={setSort}
                categories={categories}
                category={category}
                onCategory={setCategory}
                language={language}
              />
            )}
            <FeedList
              loading={feed.loading}
              error={feed.error}
              items={visible}
              onRetry={feed.reload}
              language={language}
            />
          </section>
          <CurrencyRail className="order-first xl:order-none xl:sticky xl:top-5 xl:self-start" />
        </div>
      )}
    </main>
  );
}

function Toolbar({
  count,
  sort,
  onSort,
  categories,
  category,
  onCategory,
  language,
}: {
  count: number;
  sort: SortKey;
  onSort: (s: SortKey) => void;
  categories: string[];
  category: string | null;
  onCategory: (c: string | null) => void;
  language: string;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-200 pb-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-sm font-medium text-slate-600">
          {t(language, count === 1 ? "feed.countOne" : "feed.countMany", { count })}
        </span>
        <div className="flex rounded-md bg-slate-100 p-1" aria-label={t(language, "feed.sortAria")}>
          <SortButton active={sort === "relevance"} onClick={() => onSort("relevance")}>
            {t(language, "feed.sortRelevance")}
          </SortButton>
          <SortButton active={sort === "newest"} onClick={() => onSort("newest")}>
            {t(language, "feed.sortNewest")}
          </SortButton>
        </div>
      </div>
      {categories.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={category === null} onClick={() => onCategory(null)}>
            {t(language, "feed.all")}
          </FilterChip>
          {categories.map((c) => (
            <FilterChip key={c} active={category === c} onClick={() => onCategory(c)}>
              {humanize(c)}
            </FilterChip>
          ))}
        </div>
      )}
    </div>
  );
}

function SortButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-3 py-1 text-sm font-medium transition ${
        active ? "bg-white text-slate-950 shadow-sm" : "text-slate-600 hover:text-slate-950"
      }`}
    >
      {children}
    </button>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1 text-xs font-medium transition ${
        active
          ? "border-slate-950 bg-slate-950 text-white"
          : "border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-950"
      }`}
    >
      {children}
    </button>
  );
}

function FeedList({
  loading,
  error,
  items,
  onRetry,
  language,
}: {
  loading: boolean;
  error: string | null;
  items: FeedArticle[];
  onRetry: () => void;
  language: string;
}) {
  const readIds = useReadStore((s) => s.ids);
  const markRead = useReadStore((s) => s.markRead);

  if (loading) return <Spinner label={t(language, "feed.loading")} />;
  if (error)
    return (
      <Card className="border-red-200 bg-red-50/70">
        <p className="text-sm font-semibold text-red-800">
          {t(language, "feed.unavailableTitle")}
        </p>
        <p className="mt-1 text-sm text-red-700">
          {t(language, "feed.unavailableHint")}
        </p>
        <Button className="mt-3" variant="secondary" onClick={onRetry}>
          {t(language, "common.retry")}
        </Button>
      </Card>
    );
  if (items.length === 0)
    return (
      <EmptyState
        title={t(language, "feed.noArticlesTitle")}
        hint={t(language, "feed.noArticlesHint")}
      />
    );
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
      <div className="divide-y divide-slate-100">
        {items.map((a) => (
          <ArticleCard key={a.id} article={a} read={readIds.includes(a.id)} onOpen={markRead} />
        ))}
      </div>
    </div>
  );
}

function SearchResults({
  loading,
  error,
  items,
  onClear,
  onRetry,
  language,
}: {
  loading: boolean;
  error: string | null;
  items: SearchResult[];
  onClear: () => void;
  onRetry: () => void;
  language: string;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">
          {t(language, "search.resultsTitle")}
        </h2>
        <Button variant="ghost" onClick={onClear}>
          {t(language, "search.backToFeed")}
        </Button>
      </div>
      {loading ? <Spinner label={t(language, "search.loading")} /> : null}
      {error ? (
        <Card className="border-red-200 bg-red-50/70">
          <p className="text-sm font-semibold text-red-800">
            {t(language, "search.unavailableTitle")}
          </p>
          <p className="mt-1 text-sm text-red-700">
            {t(language, "search.unavailableHint")}
          </p>
          <Button className="mt-3" variant="secondary" onClick={onRetry}>
            {t(language, "common.retry")}
          </Button>
        </Card>
      ) : null}
      {!loading && !error && items.length === 0 ? (
        <EmptyState title={t(language, "search.noResults")} />
      ) : null}
      {items.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
          <div className="divide-y divide-slate-100">
            {items.map((r) => (
              <Link
                key={r.id}
                href={`/articles/${r.id}`}
                className="block px-4 py-4 hover:bg-slate-50 sm:px-5"
              >
                <div className="text-xs font-semibold uppercase text-slate-500">{humanize(r.category)}</div>
                <h3 className="mt-1 font-semibold text-slate-950">{r.title}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-600">{r.summary}</p>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
