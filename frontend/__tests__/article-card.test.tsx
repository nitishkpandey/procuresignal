import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ArticleCard } from "@/components/article-card";
import type { FeedArticle } from "@/lib/types";

const article: FeedArticle = {
  id: 7,
  title: "Bosch strike in Poland",
  summary: "Workers began a strike.",
  category: "automotive",
  signal_tags: ["strike", "labor"],
  priority_signal: "strike",
  source_name: "Reuters",
  published_at: "2026-06-20T10:00:00Z",
  article_url: "https://example.com/a",
  relevance_score: 0.9,
  rank: 1,
};

describe("ArticleCard", () => {
  it("renders title, summary, and signals and links to detail", () => {
    render(<ArticleCard article={article} />);
    expect(screen.getByText("Bosch strike in Poland")).toBeInTheDocument();
    expect(screen.getByText("Workers began a strike.")).toBeInTheDocument();
    expect(screen.getByText("strike")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/articles/7");
  });
});
