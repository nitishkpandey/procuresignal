import { afterEach, describe, expect, it, vi } from "vitest";

// Hoisted so the mocks exist before lib/api.ts runs axios.create() at import time.
const { mockedGet, mockedPost, mockedPatch, mockedDelete } = vi.hoisted(() => ({
  mockedGet: vi.fn(),
  mockedPost: vi.fn(),
  mockedPatch: vi.fn(),
  mockedDelete: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    create: () => ({
      get: mockedGet,
      post: mockedPost,
      patch: mockedPatch,
      delete: mockedDelete,
      // lib/api installs auth interceptors on the client at import time.
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    }),
  },
}));

import * as api from "@/lib/api";

afterEach(() => {
  mockedGet.mockReset();
  mockedPost.mockReset();
  mockedPatch.mockReset();
  mockedDelete.mockReset();
});

describe("api client", () => {
  it("getFeed calls /api/feed with options", async () => {
    mockedGet.mockResolvedValue({ data: { user_id: "u1", articles: [], total_count: 0 } });
    const res = await api.getFeed({ limit: 10, days: 5, language: "de" });
    expect(mockedGet).toHaveBeenCalledWith("/api/feed", {
      params: { limit: 10, days: 5, language: "de" },
    });
    expect(res.user_id).toBe("u1");
  });

  it("getArticle forwards the requested language", async () => {
    mockedGet.mockResolvedValue({ data: { id: 7, title: "Nachricht" } });
    await api.getArticle(7, { language: "de" });
    expect(mockedGet).toHaveBeenCalledWith("/api/articles/7", {
      params: { language: "de" },
    });
  });

  it("search calls /api/search with q", async () => {
    mockedGet.mockResolvedValue({ data: { query: "tariff", total_results: 0, results: [] } });
    const res = await api.search("tariff");
    expect(mockedGet).toHaveBeenCalledWith("/api/search", {
      params: { q: "tariff", limit: 20, days: 7, language: "en" },
    });
    expect(res.query).toBe("tariff");
  });

  it("getPreferences returns null on 404", async () => {
    mockedGet.mockRejectedValue({ response: { status: 404 } });
    const res = await api.getPreferences();
    expect(res).toBeNull();
  });

  it("updatePlatformLanguage patches only language preferences", async () => {
    mockedPatch.mockResolvedValue({ data: { user_id: "u1", platform_language: "de" } });
    const res = await api.updatePlatformLanguage("de");
    expect(mockedPatch).toHaveBeenCalledWith("/api/preferences/language", {
      platform_language: "de",
    });
    expect(res.platform_language).toBe("de");
  });

  it("createConversation posts without an identity", async () => {
    mockedPost.mockResolvedValue({ data: { conversation_id: "c1", message_count: 0 } });
    const res = await api.createConversation();
    expect(mockedPost).toHaveBeenCalledWith("/api/conversations");
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

  it("getRiskEvents calls /api/risk-events with language", async () => {
    mockedGet.mockResolvedValue({ data: { user_id: "u1", events: [], total_count: 0 } });
    const res = await api.getRiskEvents({ limit: 25, language: "de" });
    expect(mockedGet).toHaveBeenCalledWith("/api/risk-events", {
      params: { limit: 25, language: "de" },
    });
    expect(res.user_id).toBe("u1");
  });

  it("updateRiskEventStatus patches status", async () => {
    mockedPatch.mockResolvedValue({ data: { id: 1, status: "reviewed" } });
    const res = await api.updateRiskEventStatus(1, "reviewed");
    expect(mockedPatch).toHaveBeenCalledWith("/api/risk-events/1/status", {
      status: "reviewed",
    });
    expect(res.status).toBe("reviewed");
  });
});
