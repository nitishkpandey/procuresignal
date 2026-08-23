"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { search, sendSearchFeedback } from "@/lib/api";
import type { FeedbackSignal, SearchResponse } from "@/lib/types";

/**
 * What the response's `mode` means to a buyer looking at the results.
 *
 * `hybrid` says nothing, because a system working as designed does not need to announce
 * itself. The other two do: results ranked by keywords alone are a different thing from
 * results a buyer is entitled to assume were ranked semantically, and letting them look
 * identical is how "search got worse" becomes an unanswerable support ticket.
 */
const MODE_NOTICE: Record<string, string | null> = {
  hybrid: null,
  lexical: "Keyword matching only — semantic search is not configured on this instance.",
  degraded: "Semantic search is unavailable right now; these are keyword results.",
};

export function SearchView() {
  const [term, setTerm] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Keyed by article id so a result the user has judged stops offering the control.
  const [judged, setJudged] = useState<Record<number, boolean>>({});

  const run = async () => {
    const query = term.trim();
    if (!query) return;

    setLoading(true);
    setError(null);
    setJudged({});
    try {
      setResponse(await search(query));
    } catch {
      setResponse(null);
      setError("Search is unavailable right now. Try again in a moment.");
    } finally {
      setLoading(false);
    }
  };

  /**
   * Feedback never blocks and never fails loudly. It is telemetry: losing a click is a
   * missing training row, while showing an error over the user's results costs them the
   * thing they came for.
   */
  const record = (articleId: number, position: number, signal: FeedbackSignal) => {
    if (!response) return;
    if (signal !== "click") setJudged((current) => ({ ...current, [articleId]: true }));
    void sendSearchFeedback({
      query: response.query,
      article_id: articleId,
      rank_position: position,
      signal,
      mode: response.mode,
    }).catch(() => undefined);
  };

  const notice = response ? MODE_NOTICE[response.mode] : null;

  return (
    <main className="space-y-5">
      <section className="border-b border-slate-200 pb-5">
        <p className="text-xs font-semibold uppercase text-slate-500">Search</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">Find what you need</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Searches the last seven days across every source, by keyword and by meaning.
        </p>
      </section>

      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <Input
          type="search"
          aria-label="Search articles"
          placeholder="port strike, semiconductor shortage, a supplier name..."
          value={term}
          onChange={(event) => setTerm(event.target.value)}
        />
        <Button type="submit" disabled={loading}>
          Search
        </Button>
      </form>

      {loading ? <Spinner /> : null}

      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      {notice ? (
        <p
          role="status"
          className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          {notice}
        </p>
      ) : null}

      {response && response.results.length === 0 && !loading ? (
        <EmptyState
          title="No results"
          hint="Nothing in the last seven days matches that. Try fewer words, or a supplier name."
        />
      ) : null}

      {response && response.results.length > 0 ? (
        <ul className="space-y-3">
          {response.results.map((result, index) => {
            const position = index + 1;
            return (
              <li key={result.id}>
                <Card className="space-y-2">
                  <Link
                    href={`/articles/${result.id}`}
                    // The signal captured from an interaction the user already performs.
                    // A thumbs-up nobody clicks produces a table nobody can train on.
                    onClick={() => record(result.id, position, "click")}
                    className="text-base font-semibold text-slate-950 hover:underline"
                  >
                    {result.title}
                  </Link>
                  <p className="text-sm text-slate-600">{result.summary}</p>
                  <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                    <span className="capitalize">{result.category}</span>
                    {judged[result.id] ? (
                      <span className="text-slate-500">Thanks — noted.</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => record(result.id, position, "not_useful")}
                        className="rounded px-2 py-1 font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
                      >
                        Not relevant
                      </button>
                    )}
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      ) : null}
    </main>
  );
}
