import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ArticleCard } from "@/components/article-card";
import type { FeedArticle } from "@/lib/types";
import { useUserStore } from "@/store/user";

const article: FeedArticle = {
  id: 7,
  title: "Bosch strike in Poland",
  summary: "Workers began a strike.",
  category: "automotive",
  signal_tags: ["strike", "labor"],
  priority_signal: "strike",
  detected_suppliers: ["Bosch"],
  detected_regions: ["Poland"],
  source_name: "Reuters",
  published_at: "2026-06-20T10:00:00Z",
  article_url: "https://example.com/a",
  relevance_score: 0.9,
  rank: 1,
};

describe("ArticleCard", () => {
  beforeEach(() => {
    localStorage.clear();
    useUserStore.setState({ userId: "u1", platformLanguage: "en" });
  });

  it("renders title, summary, and signals and links to detail", () => {
    render(<ArticleCard article={article} />);
    expect(screen.getByText("Bosch strike in Poland")).toBeInTheDocument();
    expect(screen.getByText("Workers began a strike.")).toBeInTheDocument();
    expect(screen.getAllByText("Strike").length).toBeGreaterThan(0);
    expect(
      screen.getByText((_, element) => element?.textContent === "Suppliers: Bosch"),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === "Regions: Poland"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/articles/7");
  });

  it("shows only the numeric match percentage", () => {
    render(<ArticleCard article={{ ...article, relevance_score: 0.5 }} />);
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.queryByText("Baseline match 50%")).not.toBeInTheDocument();
    expect(screen.queryByText("Medium relevance 50%")).not.toBeInTheDocument();
  });
});
