"""Language detection and validation."""

from typing import Optional

from langdetect import LangDetectException, detect


class LanguageDetector:
    """Detect and validate article language."""

    SUPPORTED_LANGUAGES = {
        "en",
        "de",
        "fr",
        "es",
        "it",
        "nl",
        "pl",
        "pt",
        "ru",
        "ja",
        "zh",
        "ko",
    }

    @staticmethod
    def detect_language(text: Optional[str]) -> Optional[str]:
        """Detect language from text.

        Args:
            text: Text to detect language from

        Returns:
            Language code (e.g., "en") or None
        """
        if not text or len(text.strip()) < 10:
            return None

        try:
            lang = detect(text)
            return lang if lang in LanguageDetector.SUPPORTED_LANGUAGES else None
        except LangDetectException:
            return None

    @staticmethod
    def is_supported_language(language: str) -> bool:
        """Check if language is supported."""
        return language in LanguageDetector.SUPPORTED_LANGUAGES


class LanguageValidator:
    """Validate article language consistency."""

    @staticmethod
    async def validate(
        title: str,
        description: Optional[str],
        content_snippet: Optional[str],
        declared_language: str,
    ) -> tuple[bool, Optional[str]]:
        """Validate language consistency.

        Returns:
            (is_valid, detected_language)
        """
        # Detect from title (most important)
        title_lang = LanguageDetector.detect_language(title)

        if title_lang is None:
            return False, None

        # Check if detected matches declared
        if declared_language != title_lang:
            # Language mismatch - might be okay for multilingual content
            # But flag it for now
            return False, title_lang

        return True, title_lang
