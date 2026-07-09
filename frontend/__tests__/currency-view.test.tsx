import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getCurrencyMonitor: vi.fn() }));
import { CurrencyView } from "@/components/currency-view";
import * as api from "@/lib/api";

beforeEach(() => {
  vi.mocked(api.getCurrencyMonitor).mockResolvedValue({
    base: "EUR",
    as_of: "2026-07-09",
    lookback_days: 30,
    currencies: [
      {
        currency: "USD",
        latest_rate: 1.2,
        range_low: 1.1,
        range_high: 1.2,
        range_position: 1,
        procurement_signal: "EUR is near its 30-day high vs USD.",
      },
    ],
  });
});

describe("CurrencyView", () => {
  it("renders EUR currency monitor signals", async () => {
    render(<CurrencyView />);

    await waitFor(() => expect(screen.getByText("EUR currency monitor")).toBeInTheDocument());
    expect(screen.getByText(/EUR \/ USD/)).toBeInTheDocument();
    expect(screen.getByText("1.2000")).toBeInTheDocument();
    expect(screen.getByText(/near its 30-day high/)).toBeInTheDocument();
  });
});
