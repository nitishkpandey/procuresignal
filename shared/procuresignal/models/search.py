"""Models for search: what is retrieved over, and what users said about it."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel

# The vocabulary the feedback columns are constrained to. Free text here would make the
# table unlearnable a year from now, when nobody remembers which spellings were in use.
FEEDBACK_SIGNALS = ("click", "useful", "not_useful")


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


class SearchFeedback(BaseModel):
    """What a user did with a search result.

    Collected from day one so that learning-to-rank has data when it is worth building.
    Nothing trains on it yet, and training on a handful of labels would be theatre.

    `rank_position` and `mode` are what make it trainable rather than merely
    interesting. A click on result 1 and a click on result 9 carry opposite information
    about the ranker, and a click under `lexical` says nothing about a ranking that ran
    in `hybrid`. Without both columns the table is a list of articles somebody once
    opened.

    `query_fingerprint` is a normalised hash, so "Port  Strike" and "port strike" are
    one query rather than two groups too small to learn from.

    `processed_article_id` is deliberately *not* a foreign key, unlike this module's
    other table. Retention prunes processed articles after 30 days; cascading would
    delete the labels with them, and a training set that can never hold more than
    30 days of feedback can never support a train/test split — which is the whole
    reason this table exists. The id is validated when it is written instead.

    `query_text` is user-entered content tied to an identified person, so this table is
    in scope for Phase 7's erasure path. That is a decision recorded now, in
    docs/personal-data-inventory.md, rather than discovered during a subject access
    request.
    """

    __tablename__ = "search_feedback"

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    query_text: Mapped[str] = mapped_column(String(200), nullable=False)
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        # A double-click is one signal, and a user who clicks, returns and clicks again
        # has not given two independent labels. Counting them twice would weight a pair
        # by how indecisive somebody was.
        UniqueConstraint(
            "user_id",
            "query_fingerprint",
            "processed_article_id",
            "signal",
            name="uq_search_feedback_signal",
        ),
        # Export is per organization; training reads by query group.
        Index("idx_search_feedback_organization", "organization_id"),
        Index("idx_search_feedback_fingerprint", "query_fingerprint"),
    )
