import logging, os
from dataclasses import dataclass
from typing import Optional
from .classify import CONFIDENCE_THRESHOLD

log = logging.getLogger(__name__)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")
HUMOR_FLAG  = "humor_manual"

@dataclass
class DraftResult:
    text: str
    flag: Optional[str]

def generate_draft(
    post_text:    str,
    category:     str,
    tone:         str,
    confidence:   float,
    tone_examples: list[str],
    recent_edits: list[dict],
) -> Optional[DraftResult]:
    """Returns None if no LLM key, low confidence, or error."""
    if not LLM_API_KEY or confidence < CONFIDENCE_THRESHOLD:
        return None
    try:
        import httpx
        from .classify import MODEL_EXPENSIVE
        system = (
            "You are a brand reputation manager writing response drafts in Russian. "
            "Always include a concrete next step. Be concise (2-4 sentences)."
        )
        if tone_examples:
            system += "\nExamples:\n" + "\n".join(f"- {e}" for e in tone_examples[:5])
        user = f"Post (category={category}, tone={tone}):\n{post_text}\n\n"
        if recent_edits:
            user += "Recent edits:\n" + "".join(
                f"  Original: {e['original']}\n  Edited: {e['edited']}\n"
                for e in recent_edits[-5:]
            )
        user += "Write a response draft. If humorous, start with [HUMOR]. Return only the draft."
        resp = httpx.post(
            LLM_API_URL,
            headers={
                "x-api-key": LLM_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL_EXPENSIVE,
                "max_tokens": 512,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"].strip()
        flag = None
        if text.startswith("[HUMOR]"):
            text, flag = text[7:].strip(), HUMOR_FLAG
        return DraftResult(text=text, flag=flag)
    except Exception:
        log.exception("Draft generation failed")
        return None
