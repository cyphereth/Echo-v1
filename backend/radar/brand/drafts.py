import json, logging, os
from dataclasses import dataclass
from typing import Optional
from .classify import CONFIDENCE_THRESHOLD

log = logging.getLogger(__name__)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")
HUMOR_FLAG  = "humor_manual"

# Comments worth a closer look: discussing promos, prices, dissatisfaction, choice.
OPPORTUNITY_TRIGGERS = [
    "акци", "скидк", "промокод", "цена", "цены", "дорого", "дешев",
    "где лучше", "посоветуй", "подскажи", "альтернатив", "разочаров",
    "не совет", "надоел", "ужас", "плохо", "верните", "обман", "лучше чем",
]


def _is_opportunity_candidate(text: str, sentiment: str) -> bool:
    """Cheap prefilter: only negative or trigger-matching comments reach Claude."""
    t = (text or "").lower()
    return sentiment == "negative" or any(trig in t for trig in OPPORTUNITY_TRIGGERS)


def _opportunity_prompts(comment_text: str, source: str,
                         competitor: Optional[str], brand_name: Optional[str]) -> tuple[str, str]:
    """Build (system, user) prompts for judging+drafting a public brand reply.
    The reply is posted openly from the brand's official account — it must read
    as the brand helping, never as an anonymous user pushing the brand."""
    brand = brand_name or "бренд"
    where = (f"под постом о конкуренте {competitor}" if (source == "competitor" and competitor)
             else "под тематическим (нишевым) постом")
    system = (
        f"Ты — SMM-менеджер бренда {brand}. Ты пишешь публичные ответы "
        f"ОТ ОФИЦИАЛЬНОГО аккаунта {brand} в комментариях соцсетей. "
        f"Читатель видит, что отвечает бренд. Твоя цель — реально помочь автору "
        f"(ответить на вопрос, дать пользу), а уже потом — мягко предложить {brand}. "
        f"Никогда не выдавай себя за обычного пользователя и не очерняй конкурентов. "
        f"Отвечай ТОЛЬКО валидным JSON без markdown."
    )
    user = (
        f'Комментарий {where}: "{comment_text}". '
        f'Есть ли здесь уместный повод для официального ответа бренда {brand}, '
        f'который сначала поможет автору? '
        f'Если да — короткий дружелюбный честный ответ от лица {brand} '
        f'(польза + мягкое предложение, без агрессии к конкуренту). '
        f'JSON: {{"is_opportunity": false, "reason": "", "reply": ""}}'
    )
    return system, user


def evaluate_opportunity(comment_text: str, source: str,
                         competitor: Optional[str], brand_name: Optional[str]) -> dict:
    """Ask Claude whether a competitor/niche comment is an opening for the brand to
    reply helpfully from the official account, and draft a transparent reply. Returns
    {is_opportunity, reason, reply} or {} on no-key/error."""
    if not LLM_API_KEY:
        return {}
    import httpx
    system, user = _opportunity_prompts(comment_text, source, competitor, brand_name)

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 250,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)

    try:
        return _call()
    except (json.JSONDecodeError, KeyError):
        try:
            return _call()
        except Exception as e:
            log.warning("evaluate_opportunity retry failed: %s", e)
            return {}
    except Exception as e:
        log.warning("evaluate_opportunity failed: %s", e)
        return {}

@dataclass
class DraftResult:
    text: str
    flag: Optional[str]


def _system_prompt(source: str, brand_name: Optional[str], tone_examples: list[str]) -> str:
    brand = brand_name or "бренд"
    if source == "competitor":
        system = (
            f"Ты пишешь короткие дружелюбные ответы ОТ ОФИЦИАЛЬНОГО аккаунта {brand} "
            f"в соцсетях. Пост касается конкурента. Не очерняя конкурента, по-доброму "
            f"предложи автору попробовать {brand} как альтернативу. По-русски, 1-3 "
            f"предложения, естественно, без спама, с мягким призывом."
        )
    elif source == "niche":
        system = (
            f"Ты пишешь короткие дружелюбные ответы ОТ ОФИЦИАЛЬНОГО аккаунта {brand} "
            f"в соцсетях. Пост по теме ниши, но {brand} не упомянут. Сначала добавь "
            f"пользы в обсуждение, затем уместно упомяни {brand}. По-русски, 1-3 "
            f"предложения, без спама."
        )
    else:
        system = (
            f"Ты — менеджер по репутации бренда {brand}, пишешь черновики ответов "
            f"ОТ ОФИЦИАЛЬНОГО аккаунта по-русски. Всегда давай конкретный следующий "
            f"шаг. Кратко (2-4 предложения)."
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
