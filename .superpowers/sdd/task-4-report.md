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
