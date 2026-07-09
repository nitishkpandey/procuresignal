"use client";

import { useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getFeed, search } from "@/lib/api";
import { humanize } from "@/lib/labels";
import { useApi } from "@/lib/useApi";
import type { FeedArticle, SearchResult } from "@/lib/types";
import { useUserStore } from "@/store/user";
import { useReadStore } from "@/store/read";
import Link from "next/link";

type SortKey = "relevance" | "newest";

export function FeedView() {
  const userId = useUserStore((s) => s.userId);
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
          <p className="text-xs font-semibold uppercase text-slate-500">Personalized signals</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-normal text-slate-950">Signal Feed</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Ranked market intelligence for your saved company profile.
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
            aria-label="Search articles"
            placeholder="Search articles..."
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </form>
      </section>

      {query ? (
        <SearchResults
          loading={results.loading}
          error={results.error}
          items={results.data?.results ?? []}
          onClear={() => {
            setQuery("");
            setDraft("");
          }}
          onRetry={results.reload}
        />
      ) : (
        <>
          {!feed.loading && !feed.error && articles.length > 0 && (
            <Toolbar
              count={visible.length}
              sort={sort}
              onSort={setSort}
              categories={categories}
              category={category}
              onCategory={setCategory}
            />
          )}
          <FeedList loading={feed.loading} error={feed.error} items={visible} onRetry={feed.reload} />
        </>
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
}: {
  count: number;
  sort: SortKey;
  onSort: (s: SortKey) => void;
  categories: string[];
  category: string | null;
  onCategory: (c: string | null) => void;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-200 pb-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-sm font-medium text-slate-600">
          {count} signal{count === 1 ? "" : "s"}
        </span>
        <div className="flex rounded-md bg-slate-100 p-1" aria-label="Sort feed">
          <SortButton active={sort === "relevance"} onClick={() => onSort("relevance")}>
            Relevance
          </SortButton>
          <SortButton active={sort === "newest"} onClick={() => onSort("newest")}>
            Newest
          </SortButton>
        </div>
      </div>
      {categories.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={category === null} onClick={() => onCategory(null)}>
            All
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
}: {
  loading: boolean;
  error: string | null;
  items: FeedArticle[];
  onRetry: () => void;
}) {
  const readIds = useReadStore((s) => s.ids);
  const markRead = useReadStore((s) => s.markRead);

  if (loading) return <Spinner label="Loading feed..." />;
  if (error)
    return (
      <Card className="border-red-200 bg-red-50/70">
        <p className="text-sm font-semibold text-red-800">Feed unavailable</p>
        <p className="mt-1 text-sm text-red-700">
          The feed service did not respond. Retry when the API is available.
        </p>
        <Button className="mt-3" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      </Card>
    );
  if (items.length === 0)
    return (
      <EmptyState
        title="No articles yet"
        hint="Preferences can be saved now; signals will appear as matching articles are processed."
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
}: {
  loading: boolean;
  error: string | null;
  items: SearchResult[];
  onClear: () => void;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">Search results</h2>
        <Button variant="ghost" onClick={onClear}>
          Back to feed
        </Button>
      </div>
      {loading ? <Spinner label="Searching..." /> : null}
      {error ? (
        <Card className="border-red-200 bg-red-50/70">
          <p className="text-sm font-semibold text-red-800">Search unavailable</p>
          <p className="mt-1 text-sm text-red-700">The search service did not respond.</p>
          <Button className="mt-3" variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        </Card>
      ) : null}
      {!loading && !error && items.length === 0 ? <EmptyState title="No results" /> : null}
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
