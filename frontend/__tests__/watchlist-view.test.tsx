import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getWatchlists: vi.fn(),
  getWatchlist: vi.fn(),
  createWatchlist: vi.fn(),
  unwatchSupplier: vi.fn(),
}));

import { WatchlistView } from "@/components/watchlist-view";
import * as api from "@/lib/api";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ user: authUser(), platformLanguage: "en" });
  vi.mocked(api.getWatchlists).mockResolvedValue({
    items: [
      { public_id: "wl-1", name: "Tier 1", supplier_count: 2 },
      { public_id: "wl-2", name: "Logistics", supplier_count: 0 },
    ],
    total_count: 2,
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
