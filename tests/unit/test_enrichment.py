"""Tests for LLM enrichment."""

import json

from procuresignal.enrichment import (
    EnrichmentOutput,
    EnrichmentPrompts,
    OutputParser,
)


def test_enrichment_output_creation():
    """Test creating EnrichmentOutput."""
    output = EnrichmentOutput(
        summary="Bosch announced a new manufacturing facility in Poland.",
        category="manufacturing",
        signal_tags=["expansion"],
        priority_signal=None,
    )

    assert output.summary == "Bosch announced a new manufacturing facility in Poland."
    assert output.category == "manufacturing"
    assert "expansion" in output.signal_tags


def test_enrichment_output_invalid_category():
    """Test that invalid category defaults to general."""
    output = EnrichmentOutput(
        summary="Test summary",
        category="invalid_category",
        signal_tags=[],
        priority_signal=None,
    )

    assert output.category == "general"


def test_enrichment_output_filters_invalid_tags():
    """Test that invalid signal tags are filtered."""
    output = EnrichmentOutput(
        summary="Test summary",
        category="manufacturing",
        signal_tags=["bankruptcy", "invalid_tag", "strike"],
        priority_signal=None,
    )

    assert "bankruptcy" in output.signal_tags
    assert "strike" in output.signal_tags
    assert "invalid_tag" not in output.signal_tags


def test_output_parser_valid_json():
    """Test parsing valid JSON response."""
    json_response = json.dumps(
        {
            "summary": "Article summary here",
            "category": "automotive",
            "signal_tags": ["tariff", "strike"],
            "priority_signal": "tariff",
        }
    )

    parsed = OutputParser.parse(json_response)

    assert parsed is not None
    assert parsed.summary == "Article summary here"
    assert parsed.category == "automotive"
    assert "tariff" in parsed.signal_tags


def test_output_parser_json_with_extra_text():
    """Test parsing JSON embedded in text."""
    response = """Here's the analysis:
{
    "summary": "Article summary here",
    "category": "manufacturing",
    "signal_tags": ["expansion"],
    "priority_signal": null
}
Some extra text here."""

    parsed = OutputParser.parse(response)

    assert parsed is not None
    assert parsed.category == "manufacturing"


def test_output_parser_invalid_json():
    """Test parsing invalid JSON returns None."""
    invalid_response = "This is not valid JSON"

    parsed = OutputParser.parse(invalid_response)

    assert parsed is None


def test_output_parser_fallback():
    """Test fallback output creation."""
    fallback = OutputParser.get_fallback("Test Article Title")

    assert fallback is not None
    assert fallback.category == "general"
    assert fallback.priority_signal is None


def test_enrichment_prompts_template():
    """Test prompt template formatting."""
    prompt = EnrichmentPrompts.get_summarization_prompt(
        title="Bosch announces facility",
        description="New manufacturing plant",
        content="Details here",
    )

    assert "Bosch announces facility" in prompt
    assert "New manufacturing plant" in prompt
    assert "Details here" in prompt
