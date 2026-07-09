"""LLM prompt templates for article enrichment."""

from procuresignal.personalization.categories import CANONICAL_CATEGORIES

CATEGORY_TEXT = ", ".join(sorted(CANONICAL_CATEGORIES))


class EnrichmentPrompts:
    """Prompts for enriching procurement articles."""

    SYSTEM_PROMPT = f"""You are an expert procurement analyst. Your task is to analyze news articles about suppliers, supply chains, and procurement topics.

You must respond with ONLY valid JSON. No markdown, no explanations, no extra text.

Your response must be valid JSON that can be parsed by Python's json.loads().

Categories: {CATEGORY_TEXT}
Priority signals: bankruptcy, m_and_a, strike, tariff, sanctions, port_strike, quality_issue

Extract suppliers as company or brand names mentioned in the article.
Extract regions as countries, regions, cities, or trade blocs mentioned in the article."""

    SUMMARIZE_PROMPT = """Analyze this procurement news article and provide:
1. A 3-5 sentence factual summary
2. Top-level category (one from: {categories})
3. List of signal tags (e.g., bankruptcy, merger, tariff, strike)
4. Whether this contains a priority signal (bankruptcy, M&A, strike, major tariff)
5. Suppliers/company names mentioned
6. Regions/locations/trade blocs mentioned
7. Category tags that apply

Title: {title}
Description: {description}
Content: {content}

Respond with ONLY this JSON structure:
{{
    "summary": "3-5 sentence summary here",
    "category": "category_name",
    "signal_tags": ["tag1", "tag2"],
    "priority_signal": "signal_name or null",
    "detected_suppliers": ["supplier1", "supplier2"],
    "detected_regions": ["region1", "region2"],
    "detected_categories": ["category1", "category2"]
}}"""

    @staticmethod
    def get_summarization_prompt(
        title: str,
        description: str,
        content: str,
    ) -> str:
        """Get summarization prompt with article data."""
        return EnrichmentPrompts.SUMMARIZE_PROMPT.format(
            categories=CATEGORY_TEXT,
            title=title,
            description=description,
            content=content,
        )
