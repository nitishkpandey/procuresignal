"use client";

import { useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
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

  const articles = feed.data?.articles ?? [];
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
    <main className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(draft.trim());
        }}
      >
        <Input
          aria-label="Search articles"
          placeholder="Search articles…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </form>

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
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-slate-500">
          {count} signal{count === 1 ? "" : "s"}
        </span>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <span>Sort</span>
          <select
            aria-label="Sort feed"
            value={sort}
            onChange={(e) => onSort(e.target.value as SortKey)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            <option value="relevance">Relevance</option>
            <option value="newest">Newest</option>
          </select>
        </label>
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
      className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
        active
          ? "border-slate-800 bg-slate-800 text-white"
          : "border-slate-300 text-slate-600 hover:border-slate-400"
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

  if (loading) return <Spinner label="Loading feed…" />;
  if (error)
    return (
      <Card>
        <p className="text-sm text-red-700">Failed to load feed: {error}</p>
        <button className="mt-2 text-sm underline" onClick={onRetry}>
          Retry
        </button>
      </Card>
    );
  if (items.length === 0)
    return <EmptyState title="No articles yet" hint="Set your preferences to personalize the feed." />;
  return (
    <div className="space-y-3">
      {items.map((a) => (
        <ArticleCard key={a.id} article={a} read={readIds.includes(a.id)} onOpen={markRead} />
      ))}
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
      <button className="text-sm underline" onClick={onClear}>
        ← Back to feed
      </button>
      {loading ? <Spinner label="Searching…" /> : null}
      {error ? (
        <p className="text-sm text-red-700">
          Search failed: {error}{" "}
          <button className="underline" onClick={onRetry}>
            Retry
          </button>
        </p>
      ) : null}
      {!loading && !error && items.length === 0 ? (
        <EmptyState title="No results" />
      ) : null}
      {items.map((r) => (
        <Card key={r.id}>
          <Link href={`/articles/${r.id}`} className="block">
            <div className="text-xs uppercase tracking-wide text-slate-500">{humanize(r.category)}</div>
            <h3 className="mt-1 font-semibold">{r.title}</h3>
            <p className="mt-1 text-sm text-slate-600">{r.summary}</p>
          </Link>
        </Card>
      ))}
    </div>
  );
}
