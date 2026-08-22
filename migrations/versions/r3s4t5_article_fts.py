"""full-text search vectors on articles

Revision ID: r3s4t5_article_fts
Revises: q2r3s4_pgvector

A generated `tsvector` per article with a GIN index, replacing `ILIKE '%term%'`.

Two columns rather than one because a STORED generated column may only reference its
own row: the enriched title and summary live on `news_articles_processed` and the
source title, description and snippet on `news_articles_raw`, and dropping either side
would narrow what the current search already finds.

Weights follow the fields' authority — title A, summary/description B, snippet C — so a
term in a headline outranks the same term buried in a body paragraph.

The configuration is chosen per row from the article's own language. `english` stemming
applied to German text produces wrong stems, which is worse than no stemming, so
languages PostgreSQL 15 ships no stemmer for (pl, ja, zh, ko) fall back to `simple`.
The `CASE` is verbose but every branch is immutable, which is what `GENERATED ALWAYS ...
STORED` requires; a `to_tsvector(text, text)` call taking the config from the column
would only be STABLE and PostgreSQL would reject it.

Deploy note: adding a STORED column rewrites the table and takes an ACCESS EXCLUSIVE
lock. The corpus is bounded by the 30-day retention policy, so the rewrite is seconds,
and building the index CONCURRENTLY afterwards would not help — the rewrite has already
taken the lock this migration needs.
"""

from alembic import op

revision = "r3s4t5_article_fts"
down_revision = "q2r3s4_pgvector"
branch_labels = None
depends_on = None

# Duplicated deliberately in shared/procuresignal/search/lexical.py, which stems the
# query side. A migration that imports live application code rewrites its own history
# the next time that code is refactored. tests/postgres/test_lexical_search_pg.py
# asserts the two agree, which is what makes the duplication safe.
CONFIGURATIONS = {
    "en": "english",
    "de": "german",
    "fr": "french",
    "es": "spanish",
    "it": "italian",
    "nl": "dutch",
    "pt": "portuguese",
    "ru": "russian",
}
FALLBACK = "simple"

PROCESSED_FIELDS = (("normalized_title", "A"), ("summary", "B"))
RAW_FIELDS = (("title", "A"), ("description", "B"), ("content_snippet", "C"))


def _weighted(fields: tuple[tuple[str, str], ...], configuration: str) -> str:
    return " || ".join(
        f"setweight(to_tsvector('{configuration}', coalesce({column}, '')), '{weight}')"
        for column, weight in fields
    )


def _expression(fields: tuple[tuple[str, str], ...]) -> str:
    branches = " ".join(
        f"WHEN '{code}' THEN {_weighted(fields, configuration)}"
        for code, configuration in CONFIGURATIONS.items()
    )
    return f"CASE language {branches} ELSE {_weighted(fields, FALLBACK)} END"


TABLES = {
    "news_articles_processed": (PROCESSED_FIELDS, "idx_processed_search_vector"),
    "news_articles_raw": (RAW_FIELDS, "idx_raw_search_vector"),
}


def upgrade() -> None:
    # SQLite has no tsvector, no GIN and no stemming. Development and the in-memory
    # suite fall back to substring matching, so this is a no-op there rather than a
    # failure that would break every existing test.
    if op.get_bind().dialect.name != "postgresql":
        return

    for table, (fields, index) in TABLES.items():
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN search_vector tsvector "
            f"GENERATED ALWAYS AS ({_expression(fields)}) STORED"
        )
        op.execute(f"CREATE INDEX {index} ON {table} USING GIN (search_vector)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table, (_fields, index) in TABLES.items():
        op.execute(f"DROP INDEX IF EXISTS {index}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS search_vector")
