// Presentation helpers: turn backend enum/snake_case values into human labels,
// and map a 0–1 relevance score to a labelled tier.

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
  label: string;
  /** Tailwind classes for the badge. */
  tone: string;
}

/** Bucket a 0–1 relevance score into High / Medium / Low with a colour. */
export function scoreTier(score: number): ScoreTier {
  if (score >= 0.66) return { label: "High", tone: "bg-red-100 text-red-800" };
  if (score >= 0.33) return { label: "Medium", tone: "bg-amber-100 text-amber-800" };
  return { label: "Low", tone: "bg-slate-100 text-slate-600" };
}

/** "2026-07-01T12:00:00" -> "Jul 1, 2026". Falls back to the raw string. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
