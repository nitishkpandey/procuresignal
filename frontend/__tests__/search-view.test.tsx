import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  search: vi.fn(),
  sendSearchFeedback: vi.fn(),
}));

import { SearchView } from "@/components/search-view";
import * as api from "@/lib/api";
import type { SearchResponse } from "@/lib/types";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

function response(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: "port strike",
    total_results: 2,
    mode: "hybrid",
    search_time_ms: 41.2,
    results: [
      {
        id: 11,
        title: "Rotterdam port strike enters second week",
        summary: "Talks between the union and terminal operators have stalled.",
        category: "logistics",
        published_at: "2026-08-22T08:00:00Z",
        relevance: 1,
      },
      {
        id: 12,
        title: "Dockworkers walk out at Europe's largest terminal",
        summary: "No containers have moved since the overnight stoppage.",
        category: "logistics",
        published_at: "2026-08-22T06:00:00Z",
        relevance: 0.82,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  // Not cleared by the project's vitest config, so call counts leak between tests and
  // an assertion that something was never called passes or fails by test order.
  vi.clearAllMocks();
  localStorage.clear();
  useUserStore.setState({ user: authUser(), platformLanguage: "en" });
  vi.mocked(api.search).mockResolvedValue(response());
  vi.mocked(api.sendSearchFeedback).mockResolvedValue(undefined);
});

async function searchFor(term = "port strike") {
  render(<SearchView />);
  await userEvent.type(screen.getByRole("searchbox"), term);
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));
}

describe("SearchView", () => {
  // Every assertion waits for loaded results rather than for markup that is present
  // while the request is still in flight.
  it("shows the results for a query", async () => {
    await searchFor();

    expect(await screen.findByText(/Rotterdam port strike enters second week/)).toBeInTheDocument();
    expect(screen.getByText(/Dockworkers walk out/)).toBeInTheDocument();
  });

  it("says keyword-only when semantic ranking did not run", async () => {
    /**
     * The mode travels in the response precisely so the UI does not imply a ranking it
     * did not get. Before the first embedding run finishes, every search is lexical.
     */
    vi.mocked(api.search).mockResolvedValue(response({ mode: "lexical" }));

    await searchFor();

    // Asserted on the notice specifically: the page subtitle also says "keyword", and a
    // looser matcher would pass with the notice missing entirely.
    expect(await screen.findByText(/keyword matching only/i)).toBeInTheDocument();
  });

  it("does not claim keyword-only when both retrievers ran", async () => {
    await searchFor();

    await screen.findByText(/Rotterdam port strike enters second week/);
    // Not queryByRole("status") — Spinner claims that role, so the assertion would be
    // about the loading state rather than about the mode notice.
    expect(screen.queryByText(/keyword matching only/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/semantic search is unavailable/i)).not.toBeInTheDocument();
  });

  it("warns when the semantic half was supposed to run and did not", async () => {
    // `degraded` is a fault, not a configuration choice, and reads differently from
    // an instance that was never given a provider.
    vi.mocked(api.search).mockResolvedValue(response({ mode: "degraded" }));

    await searchFor();

    expect(await screen.findByText(/semantic search is unavailable/i)).toBeInTheDocument();
  });

  it("records a click on the result the user opened, with its position", async () => {
    /**
     * Captured from the interaction the user already performs. A thumbs-up nobody
     * clicks produces a table nobody can train on, and the position is half the signal:
     * a click on result 1 and a click on result 9 say opposite things about the ranker.
     */
    await searchFor();

    await userEvent.click(await screen.findByRole("link", { name: /Dockworkers walk out/ }));

    await waitFor(() =>
      expect(api.sendSearchFeedback).toHaveBeenCalledWith({
        query: "port strike",
        article_id: 12,
        rank_position: 2,
        signal: "click",
        mode: "hybrid",
      }),
    );
  });

  it("offers an explicit way to say a result is wrong", async () => {
    await searchFor();

    const controls = await screen.findAllByRole("button", { name: /not relevant/i });
    await userEvent.click(controls[0]);

    await waitFor(() =>
      expect(api.sendSearchFeedback).toHaveBeenCalledWith({
        query: "port strike",
        article_id: 11,
        rank_position: 1,
        signal: "not_useful",
        mode: "hybrid",
      }),
    );
  });

  it("acknowledges the feedback so nobody clicks it twice", async () => {
    await searchFor();

    const controls = await screen.findAllByRole("button", { name: /not relevant/i });
    await userEvent.click(controls[0]);

    expect(await screen.findByText(/thanks/i)).toBeInTheDocument();
  });

  it("keeps the results when recording feedback fails", async () => {
    // Feedback is telemetry. Losing a click must never cost the user their results.
    vi.mocked(api.sendSearchFeedback).mockRejectedValue(new Error("nope"));

    await searchFor();
    const controls = await screen.findAllByRole("button", { name: /not relevant/i });
    await userEvent.click(controls[0]);

    expect(screen.getByText(/Rotterdam port strike enters second week/)).toBeInTheDocument();
  });

  it("says so when a query matches nothing", async () => {
    vi.mocked(api.search).mockResolvedValue(
      response({ results: [], total_results: 0, mode: "lexical" }),
    );

    await searchFor("sourdough");

    expect(await screen.findByText(/no results/i)).toBeInTheDocument();
  });

  it("does not search for an empty query", async () => {
    render(<SearchView />);

    await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(api.search).not.toHaveBeenCalled();
  });

  it("surfaces a failed search instead of an empty page", async () => {
    vi.mocked(api.search).mockRejectedValue(new Error("boom"));

    await searchFor();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
