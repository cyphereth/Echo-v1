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


def _system_prompt(source: str, brand_name: Optional[str], tone_examples: list[str]) -> str:
    brand = brand_name or "бренд"
    if source == "competitor":
        system = (
            f"You write short, friendly social-media replies on behalf of {brand}. "
            f"The post criticizes a COMPETITOR. Gently, without bashing the competitor, "
            f"invite the author to try {brand} as an alternative. Reply in Russian, 1-3 sentences, "
            f"natural and non-spammy. Include a soft call to action."
        )
    elif source == "niche":
        system = (
            f"You write short, friendly social-media replies on behalf of {brand}. "
            f"The post is about the niche but does NOT mention {brand}. Add value to the discussion "
            f"and mention {brand} naturally where relevant. Reply in Russian, 1-3 sentences, non-spammy."
        )
    else:
        system = (
            f"You are a brand reputation manager for {brand} writing response drafts in Russian. "
            f"Always include a concrete next step. Be concise (2-4 sentences)."
        )
    if tone_examples:
        system += "\nMatch this brand voice. Examples:\n" + "\n".join(f"- {e}" for e in tone_examples[:5])
    return system


def generate_draft(
    post_text:     str,
    category:      str,
    tone:          str,
    confidence:    float,
    tone_examples: list[str],
    recent_edits:  list[dict],
    source:        str = "brand",
    competitor:    Optional[str] = None,
    brand_name:    Optional[str] = None,
) -> Optional[DraftResult]:
    """Returns None if no LLM key, (brand-lane) low confidence, or error."""
    if not LLM_API_KEY:
        return None
    # Brand-lane drafts are gated on classifier confidence; competitor/niche
    # engagement is opportunistic and always worth a draft.
    if source == "brand" and confidence < CONFIDENCE_THRESHOLD:
        return None
    try:
        import httpx
        from .classify import MODEL_DRAFT
        system = _system_prompt(source, brand_name, tone_examples)
        ctx = f" about {competitor}" if competitor else ""
        user = f"Post (source={source}{ctx}, category={category}, tone={tone}):\n{post_text}\n\n"
        if recent_edits:
            user += "How the team edited past drafts (mirror this style):\n" + "".join(
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
                "model": MODEL_DRAFT,
                "max_tokens": 200,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        # Some API proxies return an extended thinking block before the text
        # block; find the first content item that actually has a "text" key.
        content_blocks = resp.json().get("content", [])
        text_block = next((b for b in content_blocks if b.get("type") == "text"), None)
        if not text_block:
            return None
        text = text_block["text"].strip()
        flag = None
        if text.startswith("[HUMOR]"):
            text, flag = text[7:].strip(), HUMOR_FLAG
        return DraftResult(text=text, flag=flag)
    except Exception:
        log.exception("Draft generation failed")
        return None
