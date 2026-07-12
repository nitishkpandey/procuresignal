export interface FeedArticle {
  id: number;
  title: string;
  summary: string;
  category: string;
  signal_tags: string[];
  priority_signal: string | null;
  detected_suppliers: string[];
  detected_regions: string[];
  source_name: string;
  published_at: string;
  article_url: string;
  relevance_score: number;
  rank: number;
}

export interface FeedResponse {
  user_id: string;
  articles: FeedArticle[];
  total_count: number;
  generated_at?: string;
  days_included?: number;
}

export interface SearchResult {
  id: number;
  title: string;
  summary: string;
  category: string;
  published_at: string;
  relevance: number;
}

export interface SearchResponse {
  query: string;
  total_results: number;
  results: SearchResult[];
  search_time_ms?: number;
}

export interface ArticleDetail {
  id: number;
  title: string;
  summary: string;
  description: string | null;
  content_snippet: string | null;
  category: string;
  signal_tags: string[];
  priority_signal: string | null;
  detected_suppliers: string[];
  detected_regions: string[];
  detected_categories: string[];
  source_name: string;
  source_url: string;
  article_url: string;
  published_at: string;
  processed_at: string;
  language: string;
  llm_model: string;
}

export interface Preferences {
  user_id: string;
  interested_categories: string[];
  interested_suppliers: string[];
  interested_regions: string[];
  interested_signals: string[];
  excluded_categories: string[];
  excluded_suppliers: string[];
  excluded_regions: string[];
  excluded_signals: string[];
  platform_language: string;
  created_at?: string;
  updated_at?: string;
}

export interface CurrencySignal {
  currency: string;
  latest_rate: number;
  range_low: number;
  range_high: number;
  range_position: number;
  procurement_signal: string;
}

export interface CurrencyMonitorResponse {
  base: string;
  as_of: string;
  lookback_days: number;
  currencies: CurrencySignal[];
}

export interface Conversation {
  conversation_id: string;
  title: string | null;
  message_count: number;
  last_message_at: string | null;
  created_at?: string;
}

export interface ConversationListResponse {
  user_id: string;
  conversations: Conversation[];
  total_count: number;
}

export interface ClearHistoryResponse {
  user_id: string;
  deleted_conversations: number;
  deleted_messages: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  tokens_used?: number | null;
  created_at?: string;
}

export interface MessageListResponse {
  conversation_id: string;
  messages: ChatMessage[];
  total_count: number;
}

export type ChatFrameType = "start" | "stream" | "end" | "error";

export interface ChatFrame {
  type: ChatFrameType;
  content: string;
}

export type RiskEventStatus = "new" | "reviewed" | "dismissed";

export interface RiskEvent {
  id: number;
  processed_article_id: number;
  risk_type: string;
  severity: string;
  confidence: number;
  affected_suppliers: string[];
  affected_locations: string[];
  affected_categories: string[];
  evidence_snippet: string;
  recommendation: string;
  source_name: string;
  source_url: string | null;
  published_at: string;
  status: RiskEventStatus;
  rank_score: number;
}

export interface RiskEventResponse {
  user_id: string;
  events: RiskEvent[];
  total_count: number;
  generated_at: string;
}
