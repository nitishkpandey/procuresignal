"use client";

import { useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { getFeed, search } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { FeedArticle, SearchResult } from "@/lib/types";
import { useUserStore } from "@/store/user";
import Link from "next/link";

export function FeedView() {
  const userId = useUserStore((s) => s.userId);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  const feed = useApi(() => getFeed(userId), [userId]);
  const results = useApi(
    () => (query ? search(query) : Promise.resolve(null)),
    [query],
  );

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
        <FeedList loading={feed.loading} error={feed.error} items={feed.data?.articles ?? []} onRetry={feed.reload} />
      )}
    </main>
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
        <ArticleCard key={a.id} article={a} />
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
            <div className="text-xs uppercase tracking-wide text-slate-500">{r.category}</div>
            <h3 className="mt-1 font-semibold">{r.title}</h3>
            <p className="mt-1 text-sm text-slate-600">{r.summary}</p>
          </Link>
        </Card>
      ))}
    </div>
  );
}
