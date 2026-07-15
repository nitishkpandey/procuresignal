# Task 4 Report: Registry-Driven RSS/Atom and In-Run Deduplication

## Status

Complete. `RSSProvider` now accepts one `SourceDefinition` and one safe fetcher, fetches exactly
that source, maps articles to the source's deterministic primary procurement domain, and records
the full registry provenance contract. The stale `RSSProvider.FEEDS` table was removed without an
alias. In-run deduplication canonicalizes URLs conservatively and selects the highest-authority
copy with a deterministic source/content tie-break.

## TDD evidence

- Red: the requested focused command initially stopped during collection with
  `ModuleNotFoundError: No module named 'procuresignal.retrieval.deduplication'`, demonstrating the
  missing contract before implementation.
- Green: after implementation, the focused contracts passed `16 passed in 1.18s`.
- Parsing regression discovered during green: inline Atom markup initially produced a space before
  punctuation; the sanitizer was corrected and the contract rerun green.

The worktree has no local `.venv`, so all commands used the repository environment at
`/Users/nitishkumarpandey/Desktop/procuresignal/.venv` with `PYTHONPATH=shared`.

## Verification evidence

- Focused: `pytest tests/unit/test_rss_contracts.py tests/unit/test_retrieval_deduplication.py tests/unit/test_retrieval.py -v`
  — `16 passed`.
- Full: `pytest -q` — `317 passed`.
- Static: `ruff check shared/procuresignal/retrieval tests/unit/test_rss_contracts.py tests/unit/test_retrieval_deduplication.py tests/unit/test_retrieval.py`
  — success.
- Types: `mypy shared/procuresignal/retrieval` — `Success: no issues found in 14 source files`.
- Formatting: Black completed on the changed Python files.
- Dead configuration: `rg "RSSProvider\\.FEEDS|FEEDS\\s*=" shared tests` returned no matches.
- Patch hygiene: `git diff --check` returned clean.

## Fixtures and safety boundaries

Recorded immutable fixtures cover RSS 2.0 and Atom shapes, relative and absolute links, stable
IDs, missing descriptions, German and French content, timezone offsets, HTML summaries, tracking
URL variants, and a future timestamp. No test or CI path performs live retrieval. Markup is parsed
as inert text with script/style contents suppressed and bounded output. URL normalization removes
fragments, default ports, and known tracking parameters while retaining path ordering and
content-selecting query parameters.

## Concerns

- Feed language is sourced from item/feed metadata and falls back to the registry's first declared
  language; language detection is intentionally outside this adapter contract.
- The injected `SafeFetcher` lifecycle remains caller-owned, so `RSSProvider.close()` does not
  close a shared fetcher.
- No interview document was modified.

## Commit

Pending at report creation; final commit hash is reported in the task handoff.

## Review fixes

The review findings were reproduced test-first. The expanded focused suite initially reported
`7 failed, 16 passed`, specifically demonstrating aware RSS timestamps, SQLite stripping their
timezone on persistence, input-dependent ordering across distinct deduplication groups, and
unbracketed IPv6/empty-root canonical URLs.

Corrections:

- RSS publication and retrieval timestamps are now UTC-normalized and stored as naive datetimes,
  matching the existing `TIMESTAMP WITHOUT TIME ZONE` model and NewsAPI convention. A SQLite
  model roundtrip asserts both values remain equal and naive after persistence.
- Deduplication still selects the highest-authority winner per fingerprint, then applies a stable
  total result ordering across publication time, provenance/provider identity, canonical URL,
  fingerprint, and content tie-break fields. Reversing a run containing multiple distinct groups
and a duplicate now produces the identical complete tuple. A second red test demonstrated that
same-authority records with otherwise identical identity fields still depended on input order;
publication and remaining provenance/payload fields now complete the deterministic winner key.
- URL canonicalization brackets IPv6 hosts, removes default HTTP/HTTPS ports, and normalizes an
  empty path to `/` without collapsing `/a` and `/a/`. The upstream safety-policy contract now
  explicitly covers an IPv6 loopback literal alongside its existing IPv4 and userinfo rejection.

Post-review verification:

- Focused RSS/dedup/security/retrieval suite: `29 passed in 0.94s`.
- Full suite: `322 passed in 7.30s`.
- Ruff: clean.
- Mypy retrieval package: `Success: no issues found in 14 source files`.
- Black: changed Python files formatted.

## Final total-tie review

An exact regression constructed duplicate articles with the same fingerprint, authority rank, and
all previously compared fields while changing `provider`, `query_group`, and `source_class`.
Reversing those inputs initially retained different objects, proving the remaining partial-key
defect. The winner and final-order keys now share an explicit normalized projection covering every
`RawArticle` field. Datetimes normalize to comparable UTC-naive ISO text; mappings and sets use
canonical sorted JSON; bytes, sequences, floats, and datetimes have tagged representations; and
unexpected opaque payload values reduce to stable qualified type markers rather than raising.

Final verification:

- Focused RSS/dedup/security/retrieval suite: `31 passed in 0.89s`.
- Full suite: `324 passed in 6.91s`.
- Ruff: clean.
- Mypy retrieval package: `Success: no issues found in 14 source files`.
- Black and `git diff --check`: clean.
