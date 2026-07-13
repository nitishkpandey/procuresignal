"""Canonical content fingerprints for enrichment cache identity."""

from __future__ import annotations

import hashlib
import json
import unicodedata

from procuresignal.retrieval import RawArticle


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def content_fingerprint(
    article: RawArticle,
    *,
    policy_version: str,
    taxonomy_version: str,
) -> str:
    """Return the SHA-256 digest of canonical content and policy versions."""
    fields = [
        policy_version,
        taxonomy_version,
        article.language,
        article.title,
        article.description,
        article.content_snippet,
    ]
    canonical = json.dumps([_normalize(value) for value in fields], separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
