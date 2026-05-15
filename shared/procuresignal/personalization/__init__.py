"""Personalization module."""

from .matcher import MatchScore, PreferenceMatcher
from .pipeline import PersonalizationPipeline
from .preference_manager import PreferenceManager

__all__ = [
    "PreferenceMatcher",
    "MatchScore",
    "PersonalizationPipeline",
    "PreferenceManager",
]
