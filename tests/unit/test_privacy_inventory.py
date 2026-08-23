"""The registry of personal data.

Export, erasure, retention and the Article 30 record are all derived from this one list,
because the usual way a privacy programme fails is four documents maintained separately
until they quietly disagree.

The load-bearing test is the one asserting every table in the schema is accounted for. A
table added without a decision about whether it holds personal data is an unerasable
corner nobody knows about, and it will not announce itself.
"""

import pytest
from procuresignal.models import Base
from procuresignal.privacy.inventory import (
    INVENTORY,
    ErasureAction,
    PersonalDataTable,
    SubjectLink,
    subject_tables,
    unregistered_tables,
)

BY_TABLE = {entry.table: entry for entry in INVENTORY}


def test_every_table_in_the_schema_has_a_decision() -> None:
    """Adding a table without deciding whether it holds personal data fails here rather
    than surfacing during a subject access request two years later."""

    assert unregistered_tables() == set()


def test_the_registry_never_names_a_table_that_does_not_exist() -> None:
    """A renamed table would otherwise leave the registry claiming coverage it does not
    have, and every derived document would repeat the claim."""

    assert set(BY_TABLE) - set(Base.metadata.tables) == set()


def test_no_table_is_registered_twice() -> None:
    assert len(BY_TABLE) == len(INVENTORY)


@pytest.mark.parametrize("entry", INVENTORY, ids=lambda entry: entry.table)
def test_a_link_names_a_column_that_exists(entry: PersonalDataTable) -> None:
    """The column erasure will filter on. A typo here means erasure silently finds
    nothing and reports success."""

    if entry.link is SubjectLink.NONE:
        assert entry.link_column is None
        return

    assert entry.link_column is not None
    assert entry.link_column in Base.metadata.tables[entry.table].columns


@pytest.mark.parametrize("entry", INVENTORY, ids=lambda entry: entry.table)
def test_a_table_with_no_link_is_not_erased_by_subject(entry: PersonalDataTable) -> None:
    """Nothing can be erased for a person from a table that has no way to identify one.
    A DELETE here would mean deleting somebody else's rows.
    """

    if entry.link is SubjectLink.NONE and entry.cascades_from is None:
        assert entry.erasure is ErasureAction.RETAIN, entry.table


@pytest.mark.parametrize("entry", INVENTORY, ids=lambda entry: entry.table)
def test_a_cascade_names_a_parent_that_is_registered(entry: PersonalDataTable) -> None:
    if entry.cascades_from is not None:
        assert entry.cascades_from in BY_TABLE


@pytest.mark.parametrize("entry", INVENTORY, ids=lambda entry: entry.table)
def test_every_entry_says_what_it_is_for(entry: PersonalDataTable) -> None:
    """A registry row with no purpose cannot become an Article 30 line, which is the
    whole reason the registry is machine-readable."""

    assert entry.purpose.strip()


@pytest.mark.parametrize("entry", INVENTORY, ids=lambda entry: entry.table)
def test_retained_personal_data_says_why_it_is_retained(entry: PersonalDataTable) -> None:
    """Retaining personal data through an erasure request is a lawful-basis argument.
    Every one of them is named, so the list of exceptions cannot grow silently."""

    if entry.link is not SubjectLink.NONE and entry.erasure is ErasureAction.RETAIN:
        assert entry.retention_note.strip(), entry.table


def test_the_audit_log_is_retained_and_says_on_what_ground() -> None:
    """The conflict this phase cannot engineer away.

    `audit_log` carries database triggers refusing UPDATE and DELETE, and it holds an
    actor email and a client IP. Erasing it would mean dropping the triggers, which
    destroys the guarantee for every other row. It is retained under Article 17(3), and
    that position is recorded here where the generated processing record reads it.
    """

    entry = BY_TABLE["audit_log"]

    assert entry.erasure is ErasureAction.RETAIN
    assert "17(3)" in entry.retention_note


def test_the_tables_that_link_by_public_id_are_registered_as_such() -> None:
    """Phases 1 and 2 store `User.public_id` in a string column with no foreign key.
    Deleting the user row leaves every one of them behind with a dangling identifier,
    which is the single most likely way erasure here would appear to work and not.
    """

    by_public_id = {entry.table for entry in subject_tables(SubjectLink.USER_PUBLIC_ID)}

    assert by_public_id == {
        "chat_conversations",
        "chat_messages",
        "news_article_matches",
        "user_news_feed",
        "user_news_preferences",
    }


def test_the_search_feedback_table_finally_has_an_expiry() -> None:
    """Phase 5 gave it none on purpose, so a training set could outlive the 30-day
    article window. That was a defensible engineering trade and an indefensible privacy
    position: it was the one table where personal data never expired.
    """

    entry = BY_TABLE["search_feedback"]

    assert entry.retention_days is not None
    assert entry.retention_days > 30


@pytest.mark.parametrize("entry", INVENTORY, ids=lambda entry: entry.table)
def test_a_retention_window_is_a_positive_number_of_days(entry: PersonalDataTable) -> None:
    if entry.retention_days is not None:
        assert entry.retention_days > 0


def test_subject_tables_filters_by_how_a_person_is_identified() -> None:
    integers = subject_tables(SubjectLink.USER_ID_INT)

    assert "search_feedback" in {entry.table for entry in integers}
    assert all(entry.link is SubjectLink.USER_ID_INT for entry in integers)
