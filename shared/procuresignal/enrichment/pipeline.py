"""Enrichment pipeline orchestration."""

from typing import Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from procuresignal.models import NewsArticleRaw, NewsArticleProcessed
from procuresignal.retrieval import RawArticle
from procuresignal.enrichment.enricher import ArticleEnricher
from procuresignal.enrichment.groq_client import GroqLLMClient


class EnrichmentPipeline:
    """Orchestrate the full enrichment process."""
    
    # Batch size for LLM calls
    BATCH_SIZE = 10
    
    def __init__(self, groq_client: Optional[GroqLLMClient] = None):
        """Initialize pipeline.
        
        Args:
            groq_client: Groq client instance
        """
        self.enricher = ArticleEnricher(groq_client)
        self.groq_client = groq_client or GroqLLMClient()
    
    async def process_raw_articles(
        self,
        session: AsyncSession,
        raw_articles: list[NewsArticleRaw],
    ) -> tuple[int, int, int]:
        """Process raw articles through enrichment pipeline.
        
        Args:
            session: Database session
            raw_articles: List of raw articles from database
        
        Returns:
            (enriched_count, skipped_count, error_count)
        """
        enriched_count = 0
        skipped_count = 0
        error_count = 0
        
        # Check for already-processed articles
        processed_raw_ids = set()
        existing = await session.execute(
            select(NewsArticleProcessed.raw_article_id)
        )
        for row in existing:
            processed_raw_ids.add(row[0])
        
        # Filter to unprocessed articles
        articles_to_process = [
            a for a in raw_articles
            if a.id not in processed_raw_ids
        ]
        
        # Process in batches
        for i in range(0, len(articles_to_process), self.BATCH_SIZE):
            batch = articles_to_process[i:i + self.BATCH_SIZE]
            
            # Convert to tuples (RawArticle, id)
            batch_tuples = [
                (
                    RawArticle(
                        provider=a.provider,
                        provider_article_id=a.provider_article_id,
                        query_group=a.query_group,
                        title=a.title,
                        description=a.description,
                        content_snippet=a.content_snippet,
                        article_url=a.article_url,
                        canonical_url=a.canonical_url,
                        source_name=a.source_name,
                        source_url=a.source_url,
                        published_at=a.published_at,
                        language=a.language,
                        raw_payload_json=a.raw_payload_json,
                    ),
                    a.id,
                )
                for a in batch
            ]
            
            # Enrich batch
            enriched, successes, failures = await self.enricher.enrich_batch(batch_tuples)
            
            # Save enriched articles
            saved = await self.enricher.save_enriched(session, enriched)
            
            enriched_count += saved
            error_count += failures
        
        skipped_count = len(processed_raw_ids)
        
        return enriched_count, skipped_count, error_count
    
    def get_stats(self) -> dict:
        """Get enrichment statistics."""
        return {
            **self.groq_client.get_usage_stats(),
            "model": "groq/llama-3.1-8b",
        }
