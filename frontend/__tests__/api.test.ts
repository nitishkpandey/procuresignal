import { afterEach, describe, expect, it, vi } from "vitest";

// Hoisted so the mocks exist before lib/api.ts runs axios.create() at import time.
const { mockedGet, mockedPost, mockedDelete } = vi.hoisted(() => ({
  mockedGet: vi.fn(),
  mockedPost: vi.fn(),
  mockedDelete: vi.fn(),
}));

vi.mock("axios", () => ({
  default: { create: () => ({ get: mockedGet, post: mockedPost, delete: mockedDelete }) },
}));

import * as api from "@/lib/api";

afterEach(() => {
  mockedGet.mockReset();
  mockedPost.mockReset();
  mockedDelete.mockReset();
});

describe("api client", () => {
  it("getFeed calls /api/feed with user_id and options", async () => {
    mockedGet.mockResolvedValue({ data: { user_id: "u1", articles: [], total_count: 0 } });
    const res = await api.getFeed("u1", { limit: 10, days: 5 });
    expect(mockedGet).toHaveBeenCalledWith("/api/feed", {
      params: { user_id: "u1", limit: 10, days: 5 },
    });
    expect(res.user_id).toBe("u1");
  });

  it("search calls /api/search with q", async () => {
    mockedGet.mockResolvedValue({ data: { query: "tariff", total_results: 0, results: [] } });
    const res = await api.search("tariff");
    expect(mockedGet).toHaveBeenCalledWith("/api/search", {
      params: { q: "tariff", limit: 20, days: 7 },
    });
    expect(res.query).toBe("tariff");
  });

  it("getPreferences returns null on 404", async () => {
    mockedGet.mockRejectedValue({ response: { status: 404 } });
    const res = await api.getPreferences("nobody");
    expect(res).toBeNull();
  });

  it("createConversation posts with user_id", async () => {
    mockedPost.mockResolvedValue({ data: { conversation_id: "c1", message_count: 0 } });
    const res = await api.createConversation("u1");
    expect(mockedPost).toHaveBeenCalledWith("/api/conversations", null, {
      params: { user_id: "u1" },
    });
    expect(res.conversation_id).toBe("c1");
  });

  it("getCurrencyMonitor calls /api/currency/eur-monitor", async () => {
    mockedGet.mockResolvedValue({ data: { base: "EUR", currencies: [] } });
    const res = await api.getCurrencyMonitor({ quotes: ["USD", "GBP"], days: 30 });
    expect(mockedGet).toHaveBeenCalledWith("/api/currency/eur-monitor", {
      params: { quotes: "USD,GBP", days: 30 },
    });
    expect(res.base).toBe("EUR");
  });

  it("lets the backend choose the default currency universe", async () => {
    mockedGet.mockResolvedValue({ data: { base: "EUR", currencies: [] } });
    await api.getCurrencyMonitor({ days: 30 });
    expect(mockedGet).toHaveBeenCalledWith("/api/currency/eur-monitor", {
      params: { days: 30 },
    });
  });
});
