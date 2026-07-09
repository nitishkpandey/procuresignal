"""Tests for LLM enrichment."""

import json
from datetime import datetime

import pytest
from procuresignal.enrichment import (
    ArticleEnricher,
    EnrichmentOutput,
    EnrichmentPrompts,
    OpenAILLMClient,
    OutputParser,
)
from procuresignal.retrieval import RawArticle


def test_enrichment_output_creation():
    """Test creating EnrichmentOutput."""
    output = EnrichmentOutput(
        summary="Bosch announced a new manufacturing facility in Poland.",
        category="manufacturing",
        signal_tags=["expansion"],
        priority_signal=None,
        detected_suppliers=["Bosch"],
        detected_regions=["Poland"],
        detected_categories=["manufacturing"],
    )

    assert output.summary == "Bosch announced a new manufacturing facility in Poland."
    assert output.category == "manufacturing"
    assert "expansion" in output.signal_tags
    assert output.detected_suppliers == ["Bosch"]
    assert output.detected_regions == ["Poland"]


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
            "detected_suppliers": ["Volkswagen"],
            "detected_regions": ["Germany"],
            "detected_categories": ["automotive"],
        }
    )

    parsed = OutputParser.parse(json_response)

    assert parsed is not None
    assert parsed.summary == "Article summary here"
    assert parsed.category == "automotive"
    assert "tariff" in parsed.signal_tags
    assert parsed.detected_suppliers == ["Volkswagen"]
    assert parsed.detected_regions == ["Germany"]


def test_output_parser_json_with_extra_text():
    """Test parsing JSON embedded in text."""
    response = """Here's the analysis:
{
    "summary": "Article summary here",
    "category": "manufacturing",
    "signal_tags": ["expansion"],
    "priority_signal": null,
    "detected_suppliers": ["Siemens"],
    "detected_regions": ["Germany"],
    "detected_categories": ["manufacturing"]
}
Some extra text here."""

    parsed = OutputParser.parse(response)

    assert parsed is not None
    assert parsed.category == "manufacturing"
    assert parsed.detected_suppliers == ["Siemens"]


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
    assert fallback.detected_suppliers == []
    assert fallback.detected_regions == []


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


def test_openai_client_defaults_to_low_cost_model():
    assert OpenAILLMClient.MODEL == "gpt-5.4-nano"


class _FakeOpenAIResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "Parsed response"},
                    ]
                }
            ],
            "usage": {"total_tokens": 12},
        }


class _FakeAsyncClient:
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def post(self, url, **kwargs):
        self._captured["url"] = url
        self._captured.update(kwargs)
        return _FakeOpenAIResponse()


@pytest.mark.asyncio
async def test_openai_client_uses_responses_api(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "procuresignal.enrichment.openai_client.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(captured),
    )
    client = OpenAILLMClient(api_key="test-key", model="test-model")

    result = await client.call("SYSTEM", "ARTICLE")

    assert result == "Parsed response"
    assert captured["url"].endswith("/v1/responses")
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["instructions"] == "SYSTEM"
    assert captured["json"]["input"] == "ARTICLE"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert client.get_usage_stats()["total_tokens"] == 12


class _FakeLLMClient:
    model = "test-model"

    async def call(self, system_prompt: str, user_message: str) -> str:
        return json.dumps(
            {
                "summary": "Mercedes questioned Ferrari's budget strategy in Italy.",
                "category": "automotive",
                "signal_tags": [],
                "priority_signal": None,
                "detected_suppliers": ["Mercedes", "Ferrari"],
                "detected_regions": ["Italy"],
                "detected_categories": ["automotive"],
            }
        )


@pytest.mark.asyncio
async def test_enricher_persists_detected_suppliers_and_regions():
    enricher = ArticleEnricher(_FakeLLMClient())
    article = RawArticle(
        provider="newsapi",
        provider_article_id="a1",
        query_group="automotive",
        title="Ferrari budget strategy questioned by Mercedes in Italy",
        description="Mercedes questioned Ferrari's 2026 upgrade budget.",
        content_snippet="The debate centered on Formula 1 suppliers in Italy.",
        article_url="https://example.com/a",
        canonical_url="https://example.com/a",
        source_name="Example",
        source_url="https://example.com",
        published_at=datetime.utcnow(),
        language="en",
        raw_payload_json={},
    )

    processed = await enricher.enrich(article, raw_article_id=42)

    assert processed is not None
    assert processed.detected_suppliers == ["Mercedes", "Ferrari"]
    assert processed.detected_regions == ["Italy"]
    assert processed.detected_categories == ["automotive"]
