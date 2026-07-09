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
  created_at?: string;
  updated_at?: string;
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
