import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getCurrencyMonitor: vi.fn() }));
import { CurrencyView } from "@/components/currency-view";
import * as api from "@/lib/api";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "u1", platformLanguage: "en" });
  vi.mocked(api.getCurrencyMonitor).mockResolvedValue({
    base: "EUR",
    as_of: "2026-07-09",
    lookback_days: 30,
    currencies: [
      currency("USD", 1, 1.2),
      currency("GBP", 0, 0.85),
      currency("JPY", 0.77, 185),
      currency("CHF", 0.56, 0.92),
      currency("CNY", 0.28, 7.7),
      currency("INR", 0.55, 109),
      currency("PLN", 0.95, 4.31),
      currency("CAD", 0.15, 1.55),
      currency("AUD", 0.45, 1.76),
    ],
  });
});

describe("CurrencyView", () => {
  it("renders the compact EUR timing monitor", async () => {
    render(<CurrencyView />);

    await waitFor(() => expect(screen.getByText("EUR monitor")).toBeInTheDocument());
    expect(screen.getByText("EUR / USD")).toBeInTheDocument();
    expect(screen.getByText("1.2000")).toBeInTheDocument();
    expect(screen.getAllByText("Buy window").length).toBeGreaterThan(0);
  });

  it("keeps the rail compact until the user expands all pairs", async () => {
    render(<CurrencyView />);

    await waitFor(() => expect(screen.getByText("EUR monitor")).toBeInTheDocument());
    expect(screen.getByText("Latest FX date: 2026-07-09; range window: 30 days.")).toBeInTheDocument();
    expect(screen.getByText("Showing 7 of 9 EUR pairs")).toBeInTheDocument();
    expect(screen.queryByText("EUR / AUD")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show all pairs" }));

    expect(screen.getByText("EUR / AUD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show fewer" })).toBeInTheDocument();
  });
});

function currency(code: string, position: number, latest: number) {
  return {
    currency: code,
    latest_rate: latest,
    range_low: latest - 0.1,
    range_high: latest + 0.1,
    range_position: position,
    procurement_signal: `EUR signal for ${code}.`,
  };
}
