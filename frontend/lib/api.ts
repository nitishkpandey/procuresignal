import axios from "axios";

import { installAuthInterceptors } from "@/lib/auth";

import type {
  ArticleDetail,
  ClearHistoryResponse,
  Conversation,
  ConversationListResponse,
  CurrencyMonitorResponse,
  FeedResponse,
  MessageListResponse,
  Preferences,
  RiskEvent,
  RiskEventResponse,
  RiskEventStatus,
  SearchResponse,
} from "@/lib/types";

export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

// withCredentials so the httpOnly refresh cookie rides along on /api/auth calls.
const client = axios.create({ baseURL: apiBaseUrl(), withCredentials: true });
installAuthInterceptors(client);

export async function getFeed(
  opts: { limit?: number; days?: number; language?: string } = {},
): Promise<FeedResponse> {
  const { data } = await client.get("/api/feed", {
    params: {
      limit: opts.limit ?? 50,
      days: opts.days ?? 7,
      language: opts.language ?? "en",
    },
  });
  return data;
}

export async function search(
  q: string,
  opts: { limit?: number; days?: number; language?: string } = {},
): Promise<SearchResponse> {
  const { data } = await client.get("/api/search", {
    params: {
      q,
      limit: opts.limit ?? 20,
      days: opts.days ?? 7,
      language: opts.language ?? "en",
    },
  });
  return data;
}

export async function getArticle(
  id: number,
  opts: { language?: string } = {},
): Promise<ArticleDetail> {
  const { data } = await client.get(`/api/articles/${id}`, {
    params: { language: opts.language ?? "en" },
  });
  return data;
}

export async function getCurrencyMonitor(
  opts: { quotes?: string[]; days?: number } = {},
): Promise<CurrencyMonitorResponse> {
  const params: { quotes?: string; days: number } = { days: opts.days ?? 30 };
  if (opts.quotes?.length) {
    params.quotes = opts.quotes.join(",");
  }

  const { data } = await client.get("/api/currency/eur-monitor", {
    params,
  });
  return data;
}

export async function getRiskEvents(
  opts: { limit?: number; language?: string } = {},
): Promise<RiskEventResponse> {
  const { data } = await client.get("/api/risk-events", {
    params: {
      limit: opts.limit ?? 50,
      language: opts.language ?? "en",
    },
  });
  return data;
}

export async function updateRiskEventStatus(
  id: number,
  status: RiskEventStatus,
): Promise<RiskEvent> {
  const { data } = await client.patch(`/api/risk-events/${id}/status`, { status });
  return data;
}

export async function markRead(id: number): Promise<void> {
  await client.post(`/api/articles/${id}/read`);
}

export async function getPreferences(): Promise<Preferences | null> {
  try {
    const { data } = await client.get("/api/preferences");
    return data;
  } catch (err: unknown) {
    if (typeof err === "object" && err && "response" in err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) return null;
    }
    throw err;
  }
}

export async function savePreferences(prefs: Preferences): Promise<Preferences> {
  const { data } = await client.post("/api/preferences", prefs);
  return data;
}

export async function updatePlatformLanguage(platformLanguage: string): Promise<Preferences> {
  const { data } = await client.patch("/api/preferences/language", {
    platform_language: platformLanguage,
  });
  return data;
}

export async function listConversations(): Promise<ConversationListResponse> {
  const { data } = await client.get("/api/conversations");
  return data;
}

export async function createConversation(): Promise<Conversation> {
  const { data } = await client.post("/api/conversations");
  return data;
}

export async function clearConversationHistory(): Promise<ClearHistoryResponse> {
  const { data } = await client.delete("/api/conversations");
  return data;
}

export async function getMessages(conversationId: string): Promise<MessageListResponse> {
  const { data } = await client.get(`/api/conversations/${conversationId}/messages`);
  return data;
}
