// Presentation helpers: turn backend enum/snake_case values into human labels,
// and map a 0–1 relevance score to a labelled tier.

import type { TranslationKey } from "@/lib/i18n";

const LABEL_OVERRIDES: Record<string, string> = {
  m_and_a: "M&A",
  esg: "ESG",
  it: "IT",
};

/** "supplier_risk" -> "Supplier Risk", "m_and_a" -> "M&A". */
export function humanize(value: string): string {
  if (!value) return "";
  const key = value.toLowerCase();
  if (LABEL_OVERRIDES[key]) return LABEL_OVERRIDES[key];
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface ScoreTier {
  labelKey: TranslationKey;
  /** Tailwind classes for the badge. */
  tone: string;
}

/** Bucket a 0–1 relevance score into buyer-friendly match language. */
export function scoreTier(score: number): ScoreTier {
  if (score >= 0.75) return { labelKey: "article.scoreHigh", tone: "text-red-700" };
  if (score >= 0.6) return { labelKey: "article.scoreRelevant", tone: "text-slate-700" };
  if (score >= 0.4) return { labelKey: "article.scoreBaseline", tone: "text-slate-600" };
  return { labelKey: "article.scoreLow", tone: "text-slate-500" };
}

/** "2026-07-01T12:00:00" -> "Jul 1, 2026". Falls back to the raw string. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
