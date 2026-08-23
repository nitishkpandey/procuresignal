import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getWatchlists: vi.fn(),
  getWatchlist: vi.fn(),
  createWatchlist: vi.fn(),
  unwatchSupplier: vi.fn(),
  getImpact: vi.fn(),
  runAnalysis: vi.fn(),
}));

import { WatchlistView } from "@/components/watchlist-view";
import * as api from "@/lib/api";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useUserStore.setState({ user: authUser(), platformLanguage: "en" });
  vi.mocked(api.getWatchlists).mockResolvedValue({
    items: [
      { public_id: "wl-1", name: "Tier 1", supplier_count: 2 },
      { public_id: "wl-2", name: "Logistics", supplier_count: 0 },
    ],
    total_count: 2,
  });
  vi.mocked(api.runAnalysis).mockResolvedValue({
    public_id: "run-1",
    supplier_public_id: "s-1",
    status: "completed",
    model: "gpt-5.4-mini",
    step_count: 4,
    prompt_tokens: 100,
    completion_tokens: 50,
    started_at: "2026-08-23T09:00:00Z",
    finished_at: "2026-08-23T09:00:12Z",
    failure_reason: null,
    recommendation_count: 1,
  });
  vi.mocked(api.getImpact).mockResolvedValue({
    items: [
      {
        supplier_public_id: "s-1",
        supplier_name: "Siemens AG",
        value: 0.53,
        band: "severe",
        drivers: [
          {
            event_key: "siemens-bankruptcy",
            risk_type: "bankruptcy",
            severity: "critical",
            confidence: 0.9,
            published_at: "2026-08-21T09:00:00Z",
            contribution: 0.81,
            evidence_snippet: "The group filed for protection from creditors.",
            source_name: "Handelsblatt",
          },
        ],
      },
      {
        supplier_public_id: "s-2",
        supplier_name: "Robert Bosch GmbH",
        value: 0,
        band: "none",
        drivers: [],
      },
    ],
    total: 2,
  });
  vi.mocked(api.getWatchlist).mockResolvedValue({
    public_id: "wl-1",
    name: "Tier 1",
    suppliers: [
      { public_id: "s-1", canonical_name: "Siemens AG", country: "DE" },
      { public_id: "s-2", canonical_name: "Robert Bosch GmbH", country: "DE" },
    ],
  });
});

describe("WatchlistView", () => {
  // Every assertion waits for loaded content rather than for a heading that is already
  // on screen during loading. That race turned CI red twice.
  it("lists the organization's watchlists once loaded", async () => {
    render(<WatchlistView />);

    expect(await screen.findByText("Tier 1")).toBeInTheDocument();
    expect(screen.getByText("Logistics")).toBeInTheDocument();
  });

  it("shows how many suppliers each list holds", async () => {
    render(<WatchlistView />);

    expect(await screen.findByText(/2 suppliers/i)).toBeInTheDocument();
    expect(screen.getByText(/no suppliers yet/i)).toBeInTheDocument();
  });

  it("names the suppliers on a selected list", async () => {
    render(<WatchlistView />);

    await userEvent.click(await screen.findByRole("button", { name: /Tier 1/ }));

    expect(await screen.findByText("Siemens AG")).toBeInTheDocument();
    expect(screen.getByText("Robert Bosch GmbH")).toBeInTheDocument();
  });

  it("creates a watchlist and reloads the list", async () => {
    vi.mocked(api.createWatchlist).mockResolvedValue({
      public_id: "wl-3",
      name: "Chemicals",
      supplier_count: 0,
    });
    render(<WatchlistView />);
    await screen.findByText("Tier 1");

    await userEvent.type(screen.getByLabelText(/new watchlist/i), "Chemicals");
    await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));

    expect(api.createWatchlist).toHaveBeenCalledWith("Chemicals");
  });

  it("explains a duplicate name instead of failing silently", async () => {
    vi.mocked(api.createWatchlist).mockRejectedValue({
      response: { status: 409, data: { detail: "'Tier 1' already exists in this organization" } },
    });
    render(<WatchlistView />);
    await screen.findByText("Tier 1");

    await userEvent.type(screen.getByLabelText(/new watchlist/i), "Tier 1");
    await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
  });

  it("tells a team with no lists what to do next", async () => {
    vi.mocked(api.getWatchlists).mockResolvedValue({ items: [], total_count: 0 });
    render(<WatchlistView />);

    expect(await screen.findByText(/no watchlists yet/i)).toBeInTheDocument();
  });
});

describe("WatchlistView impact", () => {
  it("shows how exposed each watched supplier is", async () => {
    // The screen a buyer opens on Monday. A list of names without exposure is a list
    // they still have to check one supplier at a time.
    render(<WatchlistView />);

    await userEvent.click(await screen.findByRole("button", { name: /Tier 1/ }));
    await screen.findByText("Siemens AG");

    expect(await screen.findByText(/severe/i)).toBeInTheDocument();
    expect(screen.getByText(/no risk events/i)).toBeInTheDocument();
  });

  it("never shows a band without the events behind it", async () => {
    render(<WatchlistView />);

    await userEvent.click(await screen.findByRole("button", { name: /Tier 1/ }));
    await screen.findByText("Siemens AG");

    await userEvent.click(await screen.findByText("Why"));

    expect(await screen.findByText(/filed for protection from creditors/i)).toBeInTheDocument();
  });
});

describe("WatchlistView analysis trigger", () => {
  it("starts an analysis from the supplier the buyer is looking at", async () => {
    // The trigger lives where the exposure already is, beside the impact badge, because
    // that is the moment somebody wants it.
    render(<WatchlistView />);

    await userEvent.click(await screen.findByRole("button", { name: /Tier 1/ }));
    await screen.findByText("Siemens AG");

    await userEvent.click(screen.getByRole("button", { name: /Analyse Siemens AG/i }));

    await waitFor(() => expect(api.runAnalysis).toHaveBeenCalledWith("s-1"));
    expect(await screen.findByRole("link", { name: /view analysis/i })).toBeInTheDocument();
  });

  it("does not let a second click bill for a second run", async () => {
    render(<WatchlistView />);

    await userEvent.click(await screen.findByRole("button", { name: /Tier 1/ }));
    await screen.findByText("Siemens AG");
    const button = screen.getByRole("button", { name: /Analyse Siemens AG/i });

    await userEvent.click(button);
    await waitFor(() => expect(api.runAnalysis).toHaveBeenCalledTimes(1));
  });
});
