"""Small Gemini REST client: no model downloads, SDK mismatch, or secret URLs."""
import math
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar

import requests

from app.config import api_key
from app.tracing import trace_step

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_deadline = ContextVar("provider_deadline", default=None)


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class InvalidModelOutput(ValueError):
    pass


@contextmanager
def request_budget(seconds: float = 100):
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def _post(model: str, method: str, payload: dict) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
        raise ValueError("Invalid Gemini model identifier")
    key = api_key()
    for attempt in range(2):
        remaining = (_deadline.get() or (time.monotonic() + 45)) - time.monotonic()
        if remaining < 2:
            raise ProviderError("The answer exceeded its time budget. Try a narrower question.", 504)
        try:
            with trace_step("gemini", {"model": model, "method": method}):
                response = requests.post(
                    f"{BASE_URL}/{model}:{method}",
                    headers={"x-goog-api-key": key}, json=payload,
                    timeout=(min(5, remaining / 4), min(30, remaining / 2)),
                )
        except requests.RequestException:
            raise ProviderError("The AI provider could not be reached. Please try again.") from None
        if response.status_code == 429:
            raise ProviderError("Gemini's quota is exhausted. Check your free-tier limits and try later.", 429)
        if response.status_code >= 500 and attempt == 0:
            time.sleep(0.5)
            continue
        if not response.ok:
            message = ("Gemini rejected the API key or model configuration."
                       if response.status_code in (400, 401, 403, 404)
                       else "The AI provider rejected the request.")
            raise ProviderError(message)
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("The AI provider returned an invalid response.") from None
        if not isinstance(data, dict):
            raise ProviderError("The AI provider returned an invalid response.")
        return data
    raise ProviderError("The AI provider is temporarily unavailable.")


def call_llm(prompt: str, max_tokens: int = 2048, model: str | None = None,
             json_mode: bool = True, system: str = "", schema: dict | None = None) -> str:
    config = {"maxOutputTokens": max_tokens, "temperature": 0}
    if json_mode:
        config["responseMimeType"] = "application/json"
    if schema:
        config["responseSchema"] = schema
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": config}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    data = _post(model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                 "generateContent", payload)
    candidates = data.get("candidates", [])
    if not candidates or candidates[0].get("finishReason") != "STOP":
        raise InvalidModelOutput("Generation was blocked or incomplete")
    text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", [])
                   if not p.get("thought"))
    if not text.strip():
        raise InvalidModelOutput("Generation was empty")
    return text


def embed(texts: list[str], task: str, model: str = "gemini-embedding-001",
          dimensions: int = 768) -> list[list[float]]:
    if not texts:
        return []
    data = _post(model, "batchEmbedContents", {"requests": [
        {"model": f"models/{model}", "content": {"parts": [{"text": text}]},
         "taskType": task, "outputDimensionality": dimensions} for text in texts
    ]})
    vectors = [item.get("values", []) for item in data.get("embeddings", [])]
    if len(vectors) != len(texts):
        raise ProviderError("The embedding provider returned an incomplete batch.")
    result = []
    for vector in vectors:
        if len(vector) != dimensions or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
            raise ProviderError("The embedding provider returned invalid vectors.")
        norm = math.sqrt(sum(v * v for v in vector))
        if not norm:
            raise ProviderError("The embedding provider returned a zero vector.")
        result.append([v / norm for v in vector])
    return result
