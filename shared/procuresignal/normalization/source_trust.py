"""Source trust and reputation management."""

from dataclasses import dataclass


@dataclass
class SourceConfig:
    """Configuration for a news source."""

    domain: str
    blocked: bool = False  # Block entirely
    low_priority: bool = False  # Include but lower rank
    trust_score: float = 0.5  # 0.0 to 1.0


class SourceTrustFilter:
    """Manage source trust and filtering."""

    # Configuration for known sources
    BLOCKED_DOMAINS = {
        "example-spam.com",
        "fake-news.ru",
        "content-farm.com",
    }

    LOW_PRIORITY_DOMAINS = {
        "aggregator.com",  # Aggregators often duplicate
        "pinterest.com",
        "instagram.com",
    }

    TRUSTED_DOMAINS = {
        "reuters.com": 0.95,
        "bloomberg.com": 0.95,
        "ft.com": 0.90,
        "wsj.com": 0.90,
        "bbc.com": 0.85,
        "cnbc.com": 0.80,
        "ec.europa.eu": 0.95,
        "govinfo.gov": 0.95,
    }

    @staticmethod
    def get_domain(url: str) -> str:
        """Extract domain from URL."""
        if not url:
            return ""

        from urllib.parse import urlparse

        parsed = urlparse(url.lower())
        domain = parsed.netloc.replace("www.", "")
        return domain

    @staticmethod
    def is_blocked(url: str) -> bool:
        """Check if source is blocked."""
        domain = SourceTrustFilter.get_domain(url)
        return domain in SourceTrustFilter.BLOCKED_DOMAINS

    @staticmethod
    def is_low_priority(url: str) -> bool:
        """Check if source is low priority."""
        domain = SourceTrustFilter.get_domain(url)
        return domain in SourceTrustFilter.LOW_PRIORITY_DOMAINS

    @staticmethod
    def get_trust_score(url: str) -> float:
        """Get trust score for domain (0.0 to 1.0)."""
        domain = SourceTrustFilter.get_domain(url)

        if domain in SourceTrustFilter.TRUSTED_DOMAINS:
            return SourceTrustFilter.TRUSTED_DOMAINS[domain]

        # Default trust score
        return 0.5
