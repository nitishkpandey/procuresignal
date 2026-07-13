# Task 2 Report: Deterministic Analysis And Pure Routing

## Status

Implemented deterministic article analysis, the pure routing decision table,
public exports, and focused unit coverage using test-first development.

## TDD evidence

1. Initial prescribed command:

   `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v`

   Result: exit 127 because this worktree has no `.venv`; zsh reported
   `.venv/bin/pytest: no such file or directory`.

2. Red run using the repository's direct virtual environment:

   `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v`

   Result: exit 2 during collection with the expected
   `ModuleNotFoundError` for `procuresignal.enrichment.deterministic` and
   `procuresignal.enrichment.router`; 0 tests collected, 2 errors.

3. Green focused run after implementation:

   `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v`

   Result: exit 0; 18 passed in 0.87s.

## Quality gates

- `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -q`
  Result: exit 0; 18 passed in 0.78s.
- `/Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/ruff check shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py`
  Result: exit 0; no issues.
- `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/mypy shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py`
  Result: exit 0; `Success: no issues found in 2 source files`.
- `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit -q`
  Result: exit 0; 152 passed in 2.51s.
- `/Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/ruff check shared/procuresignal/enrichment/__init__.py shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py`
  Result: exit 0; no issues after Ruff mechanically sorted imports.

## Design notes

- Signal tags and confidence come from `SignalClassifier` and the canonical
  signal taxonomy.
- Supplier and region evidence uses the existing entity extractors.
- Category evidence uses the existing canonical category helper, and query
  relevance uses the existing `QUERY_GROUPS` registry.
- Relevance and confidence weights are documented as exported module constants;
  each score's weights sum to 1 and scores are bounded to `[0, 1]`.
- Routing performs no I/O and does not reserve or mutate budget.

## Concerns

The worktree does not contain its own `.venv`, so verification used the direct
environment at `/Users/nitishkumarpandey/Desktop/procuresignal/.venv` with the
worktree's `shared` directory supplied through `PYTHONPATH`.

## Review fixes

Addressed all Task 2 review findings:

- summaries now ignore whitespace-only sources, retain
  description → snippet → title preference, and use a neutral deterministic
  fallback/padding marker so every output is 10–`summary_max_chars` characters;
- `summary_max_chars` now requires an `int` excluding `bool`, with an explicit
  minimum of 10;
- category resolution now scores each field through the existing
  `canonical_category` helper, weighting content above query/source metadata
  without adding category keywords.

### Review-fix TDD evidence

- Red command:
  `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py -v`
  Result: exit 1; 8 failed and 12 passed, reproducing invalid short/blank
  summaries, float/string validation failures, and query-group override.
- First green iteration of the same command:
  Result: exit 1; 1 failed and 19 passed, exposing word truncation reducing a
  padded 10-character summary to `Tiny…`.
- Final focused command:
  `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v`
  Result: exit 0; 29 passed in 0.78s.

### Review-fix quality gates

- `/Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/ruff check shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py`
  Result: exit 0; no issues.
- `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/mypy shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py`
  Result: exit 0; `Success: no issues found in 2 source files`.
- `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit -q`
  Result: exit 0; 163 passed in 2.49s.

No new concerns were identified beyond the existing shared virtual-environment
path noted above.

## Final word-boundary review fix

Word-boundary truncation now falls back to a deterministic hard prefix plus
ellipsis when the preferred whole-word result would be shorter than the
10-character `EnrichmentOutput` minimum.

- Red command:
  `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py -k word_boundary -v`
  Result: exit 1; 1 failed and 20 deselected. The produced `This is…` was only
  8 characters and failed `EnrichmentOutput` validation.
- Focused green command:
  `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v`
  Result: exit 0; 30 passed in 0.85s, including exact output `This is s…` at
  `summary_max_chars=10`.
- `/Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/ruff check shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py`
  Result: exit 0; no issues.
- `PYTHONPATH=shared /Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin/mypy shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py`
  Result: exit 0; `Success: no issues found in 2 source files`.

No additional concerns were identified.
