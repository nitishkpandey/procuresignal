import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getRiskEvents: vi.fn(),
  updateRiskEventStatus: vi.fn(),
}));

import * as api from "@/lib/api";
import { RiskEventsView } from "@/components/risk-events-view";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "buyer@example.com", platformLanguage: "en" });
  vi.mocked(api.getRiskEvents).mockResolvedValue({
    user_id: "buyer@example.com",
    total_count: 1,
    generated_at: "2026-07-12T10:00:00Z",
    events: [
      {
        id: 1,
        processed_article_id: 7,
        risk_type: "geopolitical",
        severity: "high",
        confidence: 0.82,
        affected_suppliers: [],
        affected_locations: ["Qatar"],
        affected_categories: ["energy"],
        evidence_snippet: "LNG tanker attack threatens Qatar exports.",
        recommendation: "Review supplier exposure in this region before placing large orders.",
        source_name: "Reuters",
        source_url: "https://example.com/risk",
        published_at: "2026-07-12T08:00:00Z",
        status: "new",
        rank_score: 0.9,
      },
    ],
  });
  vi.mocked(api.updateRiskEventStatus).mockResolvedValue({
    id: 1,
    processed_article_id: 7,
    risk_type: "geopolitical",
    severity: "high",
    confidence: 0.82,
    affected_suppliers: [],
    affected_locations: ["Qatar"],
    affected_categories: ["energy"],
    evidence_snippet: "LNG tanker attack threatens Qatar exports.",
    recommendation: "Review supplier exposure in this region before placing large orders.",
    source_name: "Reuters",
    source_url: "https://example.com/risk",
    published_at: "2026-07-12T08:00:00Z",
    status: "reviewed",
    rank_score: 0.9,
  });
});

describe("RiskEventsView", () => {
  it("renders risk events with a clean percentage", async () => {
    render(<RiskEventsView />);
    await waitFor(() => expect(screen.getByText("Geopolitical")).toBeInTheDocument());
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.queryByText(/match/i)).not.toBeInTheDocument();
    expect(api.getRiskEvents).toHaveBeenCalledWith("buyer@example.com", {
      language: "en",
      limit: 50,
    });
  });

  it("updates status", async () => {
    render(<RiskEventsView />);
    await waitFor(() => expect(screen.getByText("Geopolitical")).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("Status for risk event 1"), "reviewed");
    expect(api.updateRiskEventStatus).toHaveBeenCalledWith(1, "reviewed");
  });

  it("disables status changes while pending and restores the prior status on failure", async () => {
    let rejectUpdate!: (error: Error) => void;
    vi.mocked(api.updateRiskEventStatus).mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          rejectUpdate = reject;
        }),
    );

    render(<RiskEventsView />);
    await waitFor(() => expect(screen.getByText("Geopolitical")).toBeInTheDocument());
    const select = screen.getByLabelText("Status for risk event 1");

    await userEvent.selectOptions(select, "reviewed");
    expect(select).toBeDisabled();

    rejectUpdate(new Error("update failed"));
    await waitFor(() => expect(select).toHaveValue("new"));
    expect(select).not.toBeDisabled();
  });
});
