"""Article retrieval: lexical, semantic, and the fusion of the two."""

from .embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_pending_articles,
    embedding_provider,
    pending_embedding_count,
)
from .lexical import Hit, build_tsquery, lexical_search, text_search_config

__all__ = [
    "Hit",
    "build_tsquery",
    "lexical_search",
    "text_search_config",
    "EmbeddingError",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "embed_pending_articles",
    "embedding_provider",
    "pending_embedding_count",
]
