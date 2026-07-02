from __future__ import annotations
import os
import httpx

# Reuse the existing proxy integration (same as drafts.py).
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")
MODEL_DIGEST = os.getenv("LLM_MODEL_DIGEST", "claude-haiku-4-5")


class LLMNotConfigured(RuntimeError):
    """Raised when LLM_API_KEY is absent — callers should degrade gracefully."""


def complete(system: str, user: str, max_tokens: int = 1024,
             model: str | None = None) -> str:
    """One completion via the Anthropic-format proxy at LLM_API_URL.

    Mirrors drafts.py: x-api-key + anthropic-version headers, {model, max_tokens,
    system, messages} payload. Returns the first text block, stripped.
    """
    if not LLM_API_KEY:
        raise LLMNotConfigured("LLM_API_KEY not configured")
    resp = httpx.post(
        LLM_API_URL,
        headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model or MODEL_DIGEST, "max_tokens": max_tokens,
              "system": system, "messages": [{"role": "user", "content": user}]},
        timeout=120,
    )
    resp.raise_for_status()
    blocks = resp.json().get("content", [])
    return next((b["text"] for b in blocks if b.get("type") == "text"), "").strip()
