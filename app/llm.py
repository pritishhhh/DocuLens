"""
Thin wrapper around the Gemini API so every agent calls the LLM the same way
(consistent retries, consistent tracing hook).
"""

import os

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.tracing import trace_step


_client = None


def _get_client():
    """Create the Gemini client only once."""
    global _client

    if _client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY environment variable not set")

        _client = genai.Client(api_key=api_key)

    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
)
def call_llm(
    prompt: str,
    max_tokens: int = 1024,
    model: str = "gemini-2.5-flash",
    json_mode: bool = False,
) -> str:
    client = _get_client()

    config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.2,
    )

    if json_mode:
        if json_mode:
            config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(
                thinking_budget=0
            ),
    )

    with trace_step(
        "llm_call",
        {
            "model": model,
            "prompt_chars": len(prompt),
        },
    ):
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

    return response.text or ""