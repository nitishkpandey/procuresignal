import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getArticle: vi.fn() }));
import * as api from "@/lib/api";
import { ArticleDetailView } from "@/components/article-detail-view";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "u1", platformLanguage: "en" });
  vi.mocked(api.getArticle).mockResolvedValue({
    id: 5,
    title: "Tariff news",
    summary: "A summary",
    description: "desc",
    content_snippet: "snippet",
    category: "manufacturing",
    signal_tags: ["tariff"],
    priority_signal: "tariff",
    detected_suppliers: ["Bosch"],
    detected_regions: ["Germany"],
    detected_categories: ["manufacturing"],
    source_name: "Reuters",
    source_url: "https://reuters.com",
    article_url: "https://example.com/a",
    published_at: "2026-06-20T10:00:00Z",
    processed_at: "2026-06-20T11:00:00Z",
    language: "en",
    llm_model: "openai/test-model",
  });
});

describe("ArticleDetailView", () => {
  it("renders article details", async () => {
    render(<ArticleDetailView id={5} />);
    await waitFor(() => expect(screen.getByText("Tariff news")).toBeInTheDocument());
    expect(api.getArticle).toHaveBeenCalledWith(5, { language: "en" });
    expect(screen.getByText("A summary")).toBeInTheDocument();
    expect(screen.getByText("Bosch")).toBeInTheDocument();
    expect(screen.getByText("Germany")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /original article/i })).toHaveAttribute(
      "href",
      "https://example.com/a",
    );
  });

  it("requests article details in the selected platform language", async () => {
    useUserStore.setState({ userId: "u1", platformLanguage: "de" });
    render(<ArticleDetailView id={5} />);
    await waitFor(() => expect(screen.getByText("Tariff news")).toBeInTheDocument());

    expect(api.getArticle).toHaveBeenCalledWith(5, { language: "de" });
    expect(screen.getByText("Zurueck zum Feed")).toBeInTheDocument();
  });
});
