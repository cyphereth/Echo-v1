"""Ad / dropshipper / spam detection for collected posts and comments.

Two levels:
  1. looks_like_ad_cheap — instant, free rules (sales phrases, seller usernames,
     hashtag stuffing, length out of 20–150). Catches obvious commercial spam.
  2. classify_ads_batch — Claude decides human-vs-ad for survivors in one batched
     call (catches promotional tone without explicit sales phrases). Fail-open.
"""
import json, logging, os
from typing import Optional

log = logging.getLogger(__name__)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")

MIN_LEN = 20
MAX_LEN = 150
MAX_HASHTAGS = 3

SALES_PHRASES = [
    "артикул в профил", "артикул в опис", "ссылка в шапк", "ссылка в профил",
    "пиши в директ", "пишите в директ", "заказать тут", "заказать здесь",
    "промокод", "скидка по ссылк", "оптом", "доставка по росси", "в наличии",
    "закажи", "купить со скидк", "по ссылке в", "артикул:", "арт.", "цена:",
    "наш магазин", "переходи по", "переходите по", "ссылка в био", "в био",
]

SELLER_NAME_HINTS = [
    "shop", "store", "magazin", "магазин", "_opt", "opt_", "artikul",
    "market", "_wb", "wb_", "_ozon", "ozon_", "sale", "skidk", "_shop", "shop_",
]


def looks_like_ad_cheap(text: str, author: str, hashtags: Optional[list] = None,
                        min_len: int = MIN_LEN, max_len: int = MAX_LEN) -> bool:
    """Level-1 rules — no network. True = obvious ad/spam."""
    raw = text or ""
    if len(raw) < min_len or len(raw) > max_len:
        return True
    t = raw.lower()
    if any(p in t for p in SALES_PHRASES):
        return True
    a = (author or "").lower()
    if any(h in a for h in SELLER_NAME_HINTS):
        return True
    if len(hashtags or []) > MAX_HASHTAGS:
        return True
    return False


def classify_ads_batch(texts: list) -> list:
    """Level-2 — Claude human-vs-ad per text, one batched call.
    Returns list[bool] (is_ad) aligned to input. Fail-open: all False on no-key/error."""
    n = len(texts)
    if n == 0:
        return []
    if not LLM_API_KEY:
        return [False] * n

    import httpx
    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    system = (
        "Ты фильтр контента. Для каждого текста реши: это живой пост/комментарий "
        "реального человека (мнение, опыт, вопрос, мем, обсуждение) — или реклама/"
        "продажа товара (продавец, дропшиппер, промо). Отвечай ТОЛЬКО валидным JSON."
    )
    user = (
        f"Тексты:\n{numbered}\n\n"
        f'Верни JSON-массив по одному объекту на текст: '
        f'[{{"i":0,"is_ad":false}}, ...]. is_ad=true только для рекламы/продажи.'
    )

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 40 + n * 20,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)

    try:
        data = _call()
    except Exception:
        try:
            data = _call()
        except Exception as e:
            log.warning("classify_ads_batch failed: %s", e)
            return [False] * n

    flags = [False] * n
    try:
        for obj in data:
            i = obj.get("i")
            if isinstance(i, int) and 0 <= i < n:
                flags[i] = bool(obj.get("is_ad"))
    except Exception:
        return [False] * n
    return flags
