"""Parse and validate LLM output."""

import json
from dataclasses import dataclass
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class EnrichmentOutput(BaseModel):
    """Structured output from LLM enrichment."""
    
    summary: str = Field(..., min_length=10, max_length=1000)
    category: str = Field(..., min_length=3, max_length=50)
    signal_tags: List[str] = Field(default_factory=list)
    priority_signal: Optional[str] = Field(default=None)
    
    @field_validator('category', mode='before')
    def validate_category(cls, v):
        """Validate category is one of allowed values (Pydantic v2).

        Normalizes to lowercase and defaults to `general` if invalid.
        """
        try:
            val = v.lower()
        except Exception:
            return "general"

        allowed = {
            "automotive", "electronics", "chemicals", "energy",
            "manufacturing", "logistics", "regulatory", "general"
        }
        if val not in allowed:
            return "general"
        return val
    
    @field_validator('signal_tags', mode='after')
    def validate_tags(cls, v):
        """Ensure tags are valid and lowercase (Pydantic v2)."""
        allowed = {
            "bankruptcy", "m_and_a", "strike", "tariff", "sanctions",
            "port_strike", "quality_issue", "labor_dispute", "expansion"
        }
        if not isinstance(v, list):
            return []
        return [tag.lower() for tag in v if isinstance(tag, str) and tag.lower() in allowed]

    def to_json(self) -> str:
        """Return a JSON string representation compatible with Pydantic v1/v2.

        Uses `model_dump_json()` when available (pydantic v2), otherwise falls
        back to `json()` (pydantic v1).
        """
        try:
            return self.model_dump_json()
        except Exception:
            return self.json()


class OutputParser:
    """Parse and validate LLM responses."""
    
    @staticmethod
    def parse(response_text: str) -> Optional[EnrichmentOutput]:
        """Parse LLM response into structured output.
        
        Args:
            response_text: Raw text from LLM
        
        Returns:
            Parsed EnrichmentOutput or None if parsing fails
        """
        try:
            # Extract JSON from response
            # LLM might include extra text, so we look for JSON block
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                return None
            
            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)
            
            # Validate and create model
            output = EnrichmentOutput(**data)
            return output
        
        except json.JSONDecodeError:
            return None
        except ValueError:
            # Validation error
            return None
        except Exception:
            return None
    
    @staticmethod
    def get_fallback(title: str) -> EnrichmentOutput:
        """Get fallback output when LLM fails.
        
        Better to have partial data than no data.
        """
        return EnrichmentOutput(
            summary=f"Article: {title[:100]}",
            category="general",
            signal_tags=[],
            priority_signal=None,
        )
