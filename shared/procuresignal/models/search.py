"""Models for semantic search."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ArticleEmbedding(BaseModel):
    """One article's vector under one embedding model.

    `model` is on every row because distances between two vector spaces are not
    comparable: mixing `text-embedding-3-small` and `-3-large` vectors in one ranking
    produces confident nonsense, and nothing about the numbers reveals it. Every query
    filters on the active model, and a model change adds rows beside the ones currently
    serving queries rather than replacing them, which makes a rollback a filter change
    instead of a re-embedding run.

    The vector is declared without a fixed width for the same reason — `-3-large` is
    3072 dimensions and a `vector(1536)` column would reject the migration that adopts
    it. `dimensions` records what each row actually holds, and the width check that
    matters happens in code, per provider, before anything is written.

    Unlike its sibling tables, this one carries a real foreign key with ON DELETE
    CASCADE. Retention prunes processed articles after 30 days; embeddings keyed to
    deleted articles would grow without bound and rank results that no longer exist.
    A cascade cannot be forgotten the way another line in the retention job can.
    """

    __tablename__ = "article_embeddings"

    processed_article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles_processed.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    # SQLite has no vector type. Development stores JSON so the pipeline runs locally;
    # every claim about distance is verified against pgvector in tests/postgres.
    embedding: Mapped[list[float]] = mapped_column(
        Vector().with_variant(JSON(), "sqlite"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("processed_article_id", "model", name="uq_article_embedding_model"),
        Index("idx_article_embeddings_model", "model"),
    )
