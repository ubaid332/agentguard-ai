"""Thin async wrapper around the Anthropic SDK.

Centralizes model choice, structured-output parsing, and failure handling so
callers (agent.py, reasoner.py) never have to touch the SDK directly and
never crash the app if a key is missing or a request fails.
"""

from __future__ import annotations

import logging
from typing import Type, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("agentguard.llm")

T = TypeVar("T", bound=BaseModel)

_client: AsyncAnthropic | None = None


def is_available() -> bool:
    """Whether an API key is configured. Callers should always check this
    (or just try/except) rather than assume the LLM path will work."""
    return settings.llm_enabled


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def structured_call(
    *,
    system: str,
    user: str,
    output_model: Type[T],
    max_tokens: int = 2048,
) -> T | None:
    """Call the model and parse its response into `output_model`.

    Returns None (never raises) if no API key is configured or the call
    fails for any reason — callers fall back to deterministic logic.
    """
    if not is_available():
        return None

    try:
        client = _get_client()
        response = await client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            output_config={"effort": "medium"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
        )
        return response.parsed_output
    except Exception:  # noqa: BLE001 - any SDK/network failure triggers fallback
        logger.exception("LLM call failed; falling back to deterministic logic")
        return None
