"""Article enrichment orchestration."""

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleRaw, NewsArticleProcessed
from procuresignal.retrieval import RawArticle
from procuresignal.enrichment.groq_client import GroqLLMClient
from procuresignal.enrichment.prompts import EnrichmentPrompts
from procuresignal.enrichment.output_parser import OutputParser


class ArticleEnricher:
    """Enrich articles with LLM summaries and classifications."""
    
    def __init__(self, groq_client: Optional[GroqLLMClient] = None):
        """Initialize enricher.
        
        Args:
            groq_client: Groq client (created if not provided)
        """
        self.client = groq_client or GroqLLMClient()
    
    async def enrich(
        self,
        article: RawArticle,
        raw_article_id: int,
    ) -> Optional[NewsArticleProcessed]:
        """Enrich a single article.
        
        Args:
            article: Raw article from retrieval
            raw_article_id: Database ID of raw article
        
        Returns:
            Processed article or None if enrichment fails
        """
        try:
            # Prepare prompt
            prompt = EnrichmentPrompts.get_summarization_prompt(
                title=article.title,
                description=article.description or "",
                content=article.content_snippet or "",
            )
            
            # Call LLM
            response = await self.client.call(
                system_prompt=EnrichmentPrompts.SYSTEM_PROMPT,
                user_message=prompt,
            )
            
            # Parse output
            parsed = OutputParser.parse(response)
            
            # Fallback if parsing fails
            if parsed is None:
                parsed = OutputParser.get_fallback(article.title)
            
            # Create processed article
            processed = NewsArticleProcessed(
                raw_article_id=raw_article_id,
                normalized_title=article.title,
                summary=parsed.summary,
                top_level_category=parsed.category,
                signal_tags=parsed.signal_tags,
                priority_signal=parsed.priority_signal,
                detected_regions=[],  # Will be filled in Phase 6
                detected_suppliers=[],
                detected_categories=[parsed.category],
                signal_score=0.0,  # Will be calculated in Phase 6
                processing_status="completed",
                llm_model="groq/llama-3.1-8b",
                language=article.language,
                processed_at=datetime.utcnow(),
            )
            
            return processed
        
        except Exception as e:
            # Log error but don't crash
            print(f"Error enriching article {raw_article_id}: {e}")
            return None
    
    async def enrich_batch(
        self,
        articles: list[tuple[RawArticle, int]],
    ) -> tuple[list[NewsArticleProcessed], int, int]:
        """Enrich multiple articles.
        
        Args:
            articles: List of (RawArticle, raw_article_id) tuples
        
        Returns:
            (enriched_articles, successes, failures)
        """
        enriched = []
        successes = 0
        failures = 0
        
        for article, raw_id in articles:
            processed = await self.enrich(article, raw_id)
            
            if processed:
                enriched.append(processed)
                successes += 1
            else:
                failures += 1
        
        return enriched, successes, failures
    
    async def save_enriched(
        self,
        session: AsyncSession,
        processed_articles: list[NewsArticleProcessed],
    ) -> int:
        """Save enriched articles to database.
        
        Args:
            session: Database session
            processed_articles: List of processed articles
        
        Returns:
            Number saved
        """
        count = 0
        
        for article in processed_articles:
            try:
                session.add(article)
                count += 1
            except Exception:
                continue
        
        await session.commit()
        return count
