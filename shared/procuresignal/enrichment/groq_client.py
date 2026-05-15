"""Groq API client for LLM enrichment."""

import os
from typing import Optional

from groq import APIError, Groq, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class GroqLLMClient:
    """Client for Groq API (Llama 3.1)."""

    MODEL = "llama-3.1-8b-instant"
    MAX_TOKENS = 500

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Groq client.

        Args:
            api_key: Groq API key (defaults to GROQ_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")

        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set")

        self.client = Groq(api_key=self.api_key)
        self.total_tokens_used = 0
        self.total_api_calls = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIError, TimeoutError)),
    )
    async def call(
        self,
        system_prompt: str,
        user_message: str,
    ) -> str:
        """Call Groq API with retry logic.

        Args:
            system_prompt: System instructions
            user_message: User message (the article to analyze)

        Returns:
            LLM response text
        """
        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=self.MAX_TOKENS,
                temperature=0.3,
                top_p=0.9,
            )

            # Track usage
            if getattr(response, "usage", None):
                try:
                    self.total_tokens_used += response.usage.total_tokens
                except Exception:
                    pass
                self.total_api_calls += 1

            return response.choices[0].message.content

        except RateLimitError:
            raise
        except APIError:
            raise
        except Exception:
            raise

    def get_usage_stats(self) -> dict:
        """Get token usage statistics."""
        return {
            "total_tokens": self.total_tokens_used,
            "total_calls": self.total_api_calls,
            "avg_tokens_per_call": (
                self.total_tokens_used / self.total_api_calls if self.total_api_calls > 0 else 0
            ),
        }
