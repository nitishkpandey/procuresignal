"""Every table, and what it holds about a person.

One list, read by export, erasure, retention and the generated Article 30 record. Four
documents maintained separately is how a privacy programme comes apart: each is accurate
when written and none is accurate together.

Adding a table to the schema without adding it here fails a test. Tables holding no
personal data are registered too, with `SubjectLink.NONE` — a decision with a name on it
rather than an omission that looks the same as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from procuresignal.models import Base


class SubjectLink(StrEnum):
    """How a row is tied to a person.

    The two user shapes are not cosmetic. Phase 1–2 tables store `User.public_id` in a
    string column with no foreign key; Phase 4–6 tables use an integer foreign key.
    Erasure that assumes one shape misses every table of the other, and the miss looks
    exactly like success.
    """

    USER_ID_INT = "user_id_int"
    USER_PUBLIC_ID = "user_public_id"
    NONE = "none"


class ErasureAction(StrEnum):
    DELETE = "delete"
    # Keep the row, drop the person. Used where the record is somebody else's evidence:
    # a watchlist survives the colleague who made it, an approval survives its approver.
    ANONYMISE = "anonymise"
    RETAIN = "retain"


# Long enough for a full procurement cycle plus a train/test split, short enough to be a
# limit. Applied to the behavioural tables that had no expiry at all.
BEHAVIOURAL_RETENTION_DAYS = 400


@dataclass(frozen=True)
class PersonalDataTable:
    table: str
    link: SubjectLink
    link_column: str | None
    erasure: ErasureAction
    purpose: str
    retention_days: int | None = None
    # Set where a row is reached through its parent's ON DELETE CASCADE rather than by a
    # column of its own.
    cascades_from: str | None = None
    retention_note: str = ""


def _none(table: str, purpose: str, **kwargs: object) -> PersonalDataTable:
    return PersonalDataTable(
        table=table,
        link=SubjectLink.NONE,
        link_column=None,
        erasure=ErasureAction.RETAIN,
        purpose=purpose,
        **kwargs,  # type: ignore[arg-type]
    )


INVENTORY: tuple[PersonalDataTable, ...] = (
    # ---- Identity -------------------------------------------------------------------
    PersonalDataTable(
        table="users",
        link=SubjectLink.USER_ID_INT,
        link_column="id",
        erasure=ErasureAction.DELETE,
        purpose="Account identity: email, name, credentials, last sign-in.",
    ),
    PersonalDataTable(
        table="memberships",
        link=SubjectLink.USER_ID_INT,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="Which organization a person belongs to, and with what role.",
    ),
    PersonalDataTable(
        table="refresh_tokens",
        link=SubjectLink.USER_ID_INT,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="Session continuity, with the user agent and issue time of each session.",
        retention_days=90,
    ),
    PersonalDataTable(
        table="organization_invitations",
        link=SubjectLink.USER_ID_INT,
        link_column="invited_by_user_id",
        erasure=ErasureAction.ANONYMISE,
        purpose=(
            "Offers to join an organization. Holds the invitee's email address, which "
            "belongs to a different person from the inviter."
        ),
        retention_days=180,
        retention_note=(
            "The inviter is nulled on erasure so the invitation record survives; the "
            "invitee's address is erased when that person's own request is handled, or "
            "by the retention window, whichever comes first."
        ),
    ),
    # ---- What a person did ----------------------------------------------------------
    PersonalDataTable(
        table="user_news_preferences",
        link=SubjectLink.USER_PUBLIC_ID,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="The categories, suppliers, regions and risks a person asked to follow.",
    ),
    PersonalDataTable(
        table="user_news_feed",
        link=SubjectLink.USER_PUBLIC_ID,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="Which articles were surfaced to a person and which they opened.",
        retention_days=14,
    ),
    PersonalDataTable(
        table="news_article_matches",
        link=SubjectLink.USER_PUBLIC_ID,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="Why an article matched a person's profile, and how strongly.",
        retention_days=30,
    ),
    PersonalDataTable(
        table="chat_conversations",
        link=SubjectLink.USER_PUBLIC_ID,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="Conversations a person held with the assistant.",
        retention_days=BEHAVIOURAL_RETENTION_DAYS,
    ),
    PersonalDataTable(
        table="chat_messages",
        link=SubjectLink.USER_PUBLIC_ID,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose="Free-text messages a person wrote, and the replies.",
        retention_days=BEHAVIOURAL_RETENTION_DAYS,
    ),
    PersonalDataTable(
        table="search_feedback",
        link=SubjectLink.USER_ID_INT,
        link_column="user_id",
        erasure=ErasureAction.DELETE,
        purpose=(
            "What a person searched for and which results they opened or rejected. "
            "User-entered free text tied to an identified person."
        ),
        retention_days=BEHAVIOURAL_RETENTION_DAYS,
        retention_note=(
            "Phase 5 gave this table no expiry so a training set could outlive the "
            "30-day article window. Defensible as engineering, not as privacy: it was "
            "the only table where personal data never expired."
        ),
    ),
    PersonalDataTable(
        table="notifications",
        link=SubjectLink.USER_ID_INT,
        link_column="recipient_user_id",
        erasure=ErasureAction.DELETE,
        purpose="Alerts addressed to a named person, and whether they read them.",
        retention_days=180,
    ),
    # ---- Agent analyses --------------------------------------------------------------
    PersonalDataTable(
        table="agent_runs",
        link=SubjectLink.USER_ID_INT,
        link_column="requested_by_user_id",
        erasure=ErasureAction.DELETE,
        purpose="Which supplier a named person asked to have analysed, and when.",
        retention_days=BEHAVIOURAL_RETENTION_DAYS,
    ),
    _none(
        "agent_steps",
        "Tool calls and model replies within a run. No column of its own identifies a person.",
        cascades_from="agent_runs",
    ),
    PersonalDataTable(
        table="agent_recommendations",
        link=SubjectLink.USER_ID_INT,
        link_column="decided_by_user_id",
        erasure=ErasureAction.ANONYMISE,
        purpose="Proposed mitigations and who approved or rejected each one.",
        cascades_from="agent_runs",
        retention_note=(
            "The approver is nulled rather than the decision deleted: an approval trail "
            "that disappears with its author is not a trail. The row itself goes when "
            "the run does."
        ),
    ),
    # ---- Organization-owned records that name a colleague ----------------------------
    PersonalDataTable(
        table="watchlists",
        link=SubjectLink.USER_ID_INT,
        link_column="created_by_user_id",
        erasure=ErasureAction.ANONYMISE,
        purpose="Supplier lists an organization keeps, and who created each.",
        retention_note=(
            "The list belongs to the organization and its colleagues still depend on "
            "it, so only the author is removed."
        ),
    ),
    PersonalDataTable(
        table="watchlist_entries",
        link=SubjectLink.USER_ID_INT,
        link_column="added_by_user_id",
        erasure=ErasureAction.ANONYMISE,
        purpose="Which supplier is on which list, and who added it.",
        retention_note="As watchlists: the entry outlives the colleague who added it.",
    ),
    PersonalDataTable(
        table="alert_rules",
        link=SubjectLink.USER_ID_INT,
        link_column="created_by_user_id",
        erasure=ErasureAction.ANONYMISE,
        purpose="Alerting rules an organization configured, and who wrote each.",
        retention_note=(
            "Deleting the rule would stop the organization's alerts when a colleague "
            "leaves, which is a availability failure dressed as a privacy control."
        ),
    ),
    # ---- The trail ---------------------------------------------------------------------
    PersonalDataTable(
        table="audit_log",
        link=SubjectLink.USER_ID_INT,
        link_column="actor_user_id",
        erasure=ErasureAction.RETAIN,
        purpose=(
            "Who did what, from which address. Holds an actor email, a client IP and a "
            "user agent."
        ),
        retention_note=(
            "Retained under Article 17(3)(b) and (e): it is the evidence that access "
            "controls over procurement data worked, and the table carries database "
            "triggers refusing UPDATE and DELETE. Erasing a row would mean dropping "
            "those triggers, destroying the guarantee for every other row. OWNER INPUT "
            "REQUIRED: this ground needs legal confirmation."
        ),
    ),
    _none(
        "dead_letters",
        "Task payloads and tracebacks from work that exhausted its retries.",
        retention_days=30,
        retention_note=(
            "No column identifies a person, but a stored payload may incidentally "
            "contain a user id. Bounded by the retention window rather than by erasure, "
            "because the payload shape is not knowable in advance."
        ),
    ),
    # ---- No personal data --------------------------------------------------------------
    _none("organizations", "Tenant records: name and slug."),
    _none("suppliers", "The canonical supplier registry."),
    _none("supplier_aliases", "Spellings that resolve to a supplier."),
    _none("article_supplier_mentions", "Which suppliers an article names."),
    _none("news_articles_raw", "Ingested articles as published.", retention_days=14),
    _none("news_articles_processed", "Enriched articles.", retention_days=30),
    _none(
        "article_embeddings", "Vectors over article text.", cascades_from="news_articles_processed"
    ),
    _none("risk_events", "Procurement risks detected from articles.", retention_days=14),
    _none("signals", "Signal records derived from articles."),
    _none("signal_metadata", "Metadata about a signal."),
    _none("signal_supply_chain_impact", "Impact assessments attached to a signal."),
    _none("news_pipeline_runs", "Pipeline execution records."),
    _none("news_priority_events", "Priority events raised by the pipeline."),
    _none("news_retrieval_runs", "Retrieval run audit records."),
    _none("news_retrieval_source_outcomes", "Per-source outcomes within a retrieval run."),
    _none("news_retrieval_circuits", "Circuit-breaker state per source."),
    _none("enrichment_cache", "Cached enrichment output, keyed by content fingerprint."),
    _none("llm_spend", "Token spend per tenant per day. Aggregate, never per person."),
)


def subject_tables(link: SubjectLink) -> tuple[PersonalDataTable, ...]:
    """Registered tables identified by a particular kind of link."""

    return tuple(entry for entry in INVENTORY if entry.link is link)


def unregistered_tables() -> set[str]:
    """Tables in the schema that nobody has made a decision about.

    Compared against `Base.metadata`, which is the schema this codebase declares.
    `alembic_version` is created by Alembic itself and is deliberately absent from both:
    it holds a revision string and nothing else.

    The check that keeps this file honest: a table added without an entry here is an
    unerasable corner, and it will not announce itself.
    """

    return set(Base.metadata.tables) - {entry.table for entry in INVENTORY}
