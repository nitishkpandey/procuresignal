import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getFeed: vi.fn(),
  search: vi.fn(),
}));
import * as api from "@/lib/api";
import { FeedView } from "@/components/feed-view";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "u1" });
  vi.mocked(api.getFeed).mockResolvedValue({
    user_id: "u1",
    total_count: 1,
    articles: [
      {
        id: 1,
        title: "Feed article",
        summary: "s",
        category: "automotive",
        signal_tags: [],
        priority_signal: null,
        detected_suppliers: [],
        detected_regions: [],
        source_name: "Reuters",
        published_at: "2026-06-20T10:00:00Z",
        article_url: "https://e.com",
        relevance_score: 0.5,
        rank: 1,
      },
    ],
  });
  vi.mocked(api.search).mockResolvedValue({
    query: "tariff",
    total_results: 1,
    results: [
      {
        id: 2,
        title: "Search hit",
        summary: "s2",
        category: "manufacturing",
        published_at: "2026-06-20T10:00:00Z",
        relevance: 0.8,
      },
    ],
  });
});

describe("FeedView", () => {
  it("renders the feed by default", async () => {
    render(<FeedView />);
    await waitFor(() => expect(screen.getByText("Feed article")).toBeInTheDocument());
  });

  it("shows search results after submitting a query", async () => {
    render(<FeedView />);
    await waitFor(() => expect(screen.getByText("Feed article")).toBeInTheDocument());
    const input = screen.getByLabelText("Search articles");
    await userEvent.type(input, "tariff{enter}");
    await waitFor(() => expect(screen.getByText("Search hit")).toBeInTheDocument());
    expect(screen.queryByText("Feed article")).not.toBeInTheDocument();
  });

  it("shows a retry control when search fails", async () => {
    vi.mocked(api.search).mockRejectedValueOnce(new Error("boom"));
    render(<FeedView />);
    await waitFor(() => expect(screen.getByText("Feed article")).toBeInTheDocument());
    const input = screen.getByLabelText("Search articles");
    await userEvent.type(input, "tariff{enter}");
    await waitFor(() => expect(screen.getByText("Search unavailable")).toBeInTheDocument());
    expect(screen.getByText(/The search service did not respond/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows a professional retry state when the feed fails", async () => {
    vi.mocked(api.getFeed).mockRejectedValueOnce(new Error("Network Error"));
    render(<FeedView />);
    await waitFor(() => expect(screen.getByText("Feed unavailable")).toBeInTheDocument());
    expect(screen.getByText(/The feed service did not respond/)).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load feed/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
