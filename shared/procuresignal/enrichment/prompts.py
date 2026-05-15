"""LLM prompt templates for article enrichment."""


class EnrichmentPrompts:
    """Prompts for enriching procurement articles."""
    
    SYSTEM_PROMPT = """You are an expert procurement analyst. Your task is to analyze news articles about suppliers, supply chains, and procurement topics.

You must respond with ONLY valid JSON. No markdown, no explanations, no extra text.

Your response must be valid JSON that can be parsed by Python's json.loads().

Categories: automotive, electronics, chemicals, energy, manufacturing, logistics, regulatory, general
Priority signals: bankruptcy, m_and_a, strike, tariff, sanctions, port_strike, quality_issue"""
    
    SUMMARIZE_PROMPT = """Analyze this procurement news article and provide:
1. A 3-5 sentence factual summary
2. Top-level category (one from: automotive, electronics, chemicals, energy, manufacturing, logistics, regulatory, general)
3. List of signal tags (e.g., bankruptcy, merger, tariff, strike)
4. Whether this contains a priority signal (bankruptcy, M&A, strike, major tariff)

Title: {title}
Description: {description}
Content: {content}

Respond with ONLY this JSON structure:
{{
    "summary": "3-5 sentence summary here",
    "category": "category_name",
    "signal_tags": ["tag1", "tag2"],
    "priority_signal": "signal_name or null"
}}"""
    
    @staticmethod
    def get_summarization_prompt(
        title: str,
        description: str,
        content: str,
    ) -> str:
        """Get summarization prompt with article data."""
        return EnrichmentPrompts.SUMMARIZE_PROMPT.format(
            title=title,
            description=description,
            content=content,
        )
