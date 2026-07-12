# Task 1 Report: Risk Taxonomy And Detector

## Status

Implemented Task 1 on branch `codex/risk-event-layer-design`.

## Files changed

- `shared/procuresignal/risk_events/__init__.py`
- `shared/procuresignal/risk_events/taxonomy.py`
- `shared/procuresignal/risk_events/detector.py`
- `tests/unit/test_risk_event_detector.py`

## Implementation

- Added the procurement risk taxonomy, canonical risk normalization, aliases, severity defaults, and recommendations.
- Added `RiskEventCandidate` and deterministic article-level detection.
- Reused existing signal-term expansion, whole-term matching, and region canonicalization helpers.
- Added the deliberate rule that geopolitical aliases expand into regional-conflict aliases, including `red sea` for `war`.
- Collapsed geopolitical and regional-conflict matches to the single strongest event for an article.
- Used explicit processed region metadata when available, with text extraction as a fallback.

## Verification

- Prescribed command: `poetry run pytest tests/unit/test_risk_event_detector.py -q`
  - Could not run because `poetry` is not installed in the environment.
- Equivalent local command: `PYTHONPATH=shared ./.venv/bin/pytest tests/unit/test_risk_event_detector.py -q`
  - Result: `4 passed`.
- `PYTHONPATH=shared ./.venv/bin/ruff check shared/procuresignal/risk_events tests/unit/test_risk_event_detector.py`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## Remaining Review Fixes

- Merged processed `detected_regions` with regions extracted from article text, then canonicalized and deduplicated the combined locations.
- Kept `risk_terms_for(["war"])` regional alias expansion intact while requiring a geopolitical action term before emitting geopolitical or regional-conflict events.
- Added regression coverage for a processed location plus a distinct text-only location, and for benign Qatar investment news with location mentions but no conflict language.

## Remaining Review Fix Verification

- `PYTHONPATH=shared ./.venv/bin/pytest tests/unit/test_risk_event_detector.py -q`
  - Result: `8 passed`.
- `PYTHONPATH=shared ./.venv/bin/ruff check shared/procuresignal/risk_events/detector.py shared/procuresignal/risk_events/taxonomy.py tests/unit/test_risk_event_detector.py`
  - Result: passed.
- `git diff --check`
  - Result: passed.

## Scope and artifacts

Only the four Task 1 files were staged and committed. Existing unrelated untracked artifacts were left untouched and were not staged.

## Review Fix

- Included `raw.content_snippet` in article text so snippet-only risk evidence is detected.
- Allowed explicit text risk matches even when existing signal metadata is present but unrelated.
- Added regression coverage for snippet-only bankruptcy detection and unrelated `supplier_risk` metadata alongside explicit bankruptcy text.

## Review Fix Verification

- `PYTHONPATH=shared ./.venv/bin/pytest tests/unit/test_risk_event_detector.py -q`
  - Result: `6 passed`.
- `PYTHONPATH=shared ./.venv/bin/ruff check shared/procuresignal/risk_events/detector.py shared/procuresignal/risk_events/taxonomy.py tests/unit/test_risk_event_detector.py`
  - Result: passed.
- `git diff --check`
  - Result: passed.
