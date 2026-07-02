"""Ad / dropshipper / spam detection for collected posts and comments.

Two levels:
  1. looks_like_ad_cheap — instant, free, sphere-INDEPENDENT rules (too-short text,
     dropshipper/seller usernames). Catches only universal junk.
  2. classify_ads_batch — Claude decides noise-vs-relevant for survivors in one batched
     call, judged for the brand's sphere (so marketplace and food get different calls).
     Fail-open.
"""
import json, logging, os, re
from typing import Optional

log = logging.getLogger(__name__)

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")

MIN_LEN = 20

SELLER_NAME_HINTS = [
    "shop", "store", "magazin", "магазин", "_opt", "opt_", "artikul",
    "market", "_wb", "wb_", "_ozon", "ozon_", "sale", "skidk", "_shop", "shop_",
]


PROVIDER_NAME_HINTS = ["nails", "nail", "brows", "brow", "makeup", "lash", "studio",
    "beauty", "salon", "мастер", "master", "stylist", "barber", "manicure", "permanent"]
PROVIDER_PHRASES = ["запись", "записаться", "по записи", "записывайтесь", "прайс",
    "услуги", "директ для записи", "запись в директ", "коррекция", "наращивание",
    "свободные окошки", "свободное время", "адрес студии"]


def looks_like_provider_cheap(text: str, author: str) -> bool:
    """A service provider (master/salon/business) rather than a regular person.
    Used in local_mode to route providers to the competitor lane."""
    a = (author or "").lower()
    # Hint must be a segment of the handle (bounded by . _ digits / ends), not a
    # substring inside a word — otherwise "nail" matches "Наилевна" (a patronymic).
    for h in PROVIDER_NAME_HINTS:
        if re.search(r"(?<![a-zа-яё])" + re.escape(h) + r"(?![a-zа-яё])", a):
            return True
    t = (text or "").lower()
    return any(p in t for p in PROVIDER_PHRASES)


def classify_providers_batch(texts: list) -> list:
    """Claude per text: service PROVIDER (master/salon/business) vs regular person
    (potential client)? Returns list[bool] is_provider. Fail-open = all False."""
    n = len(texts)
    if n == 0:
        return []
    if not LLM_API_KEY:
        return [False] * n
    import httpx
    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    system = (
        "Ты фильтр аудитории. Для каждого текста реши: это аккаунт ПРОВАЙДЕРА услуг "
        "(мастер, салон, студия, бизнес — предлагает услуги/записи) или ОБЫЧНЫЙ человек "
        "(потенциальный клиент, делится жизнью). Отвечай ТОЛЬКО валидным JSON."
    )
    user = (
        f"Тексты:\n{numbered}\n\n"
        f'Верни JSON-массив: [{{"i":0,"is_provider":false}}, ...]. '
        f'is_provider=true только для мастеров/салонов/бизнеса.'
    )

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 40 + n * 20,
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
            log.warning("classify_providers_batch failed: %s", e)
            return [False] * n
    flags = [False] * n
    try:
        for obj in data:
            i = obj.get("i")
            if isinstance(i, int) and 0 <= i < n:
                flags[i] = bool(obj.get("is_provider"))
    except Exception:
        return [False] * n
    return flags


def looks_like_ad_cheap(text: str, author: str, hashtags: Optional[list] = None,
                        min_len: int = MIN_LEN) -> bool:
    """Level-1 UNIVERSAL junk — no network, sphere-independent. True only for junk in
    EVERY sphere: too-short text, or a dropshipper/seller handle. Sphere-specific noise
    (marketplace sales phrases, heavy hashtags, long promos) is left to the sphere-aware
    AI judge in classify_ads_batch."""
    raw = text or ""
    if len(raw) < min_len:
        return True
    a = (author or "").lower()
    if any(h in a for h in SELLER_NAME_HINTS):
        return True
    return False


def _build_ads_classify_payload(texts: list, sphere: str = "") -> dict:
    """Anthropic request for the sphere-aware noise judge. Marks NOISE (foreign
    ads/sellers, off-topic) vs RELEVANT mentions, judged for the brand's sphere."""
    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    ctx = f'Бренд работает в сфере: "{sphere}". ' if sphere else ""
    system = (
        "Ты фильтр релевантности для мониторинга бренда. " + ctx +
        "Для каждого текста реши: это ШУМ (чужая реклама, продавец-дропшиппер, "
        "оффтоп, не относится к сфере бренда) — или РЕЛЕВАНТНЫЙ пост/упоминание "
        "(мнение, опыт, вопрос, обсуждение по теме бренда). Отвечай ТОЛЬКО валидным JSON."
    )
    user = (
        f"Тексты:\n{numbered}\n\n"
        f'Верни JSON-массив по одному объекту на текст: '
        f'[{{"i":0,"is_ad":false}}, ...]. is_ad=true только для шума.'
    )
    return {"model": "claude-haiku-4-5", "max_tokens": 40 + len(texts) * 20,
            "system": system, "messages": [{"role": "user", "content": user}]}


def _build_disambiguate_payload(texts: list, brand_name: str, sphere: str = "") -> dict:
    """Anthropic request for brand-lane disambiguation. Each text already matched a
    brand keyword; decide whether it is really about the brand or an unrelated meaning
    of the word (homonym/off-topic). Default-keep: flag off-topic only when confident."""
    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    sph = f' в сфере "{sphere}"' if sphere else ""
    system = (
        f'Каждый текст упоминает бренд "{brand_name}"{sph}. Реши: текст действительно '
        f'про ЭТОТ бренд — или это ДРУГОЕ значение слова (игра, животное, имя, оффтоп, '
        f'не относится к сфере бренда)? По умолчанию считай, что про бренд; помечай '
        f'off-topic ТОЛЬКО при явной уверенности. Отвечай ТОЛЬКО валидным JSON.'
    )
    user = (
        f"Тексты:\n{numbered}\n\n"
        f'Верни JSON-массив по одному объекту на текст: '
        f'[{{"i":0,"is_offtopic":false}}, ...]. is_offtopic=true только для явного оффтопа.'
    )
    return {"model": "claude-haiku-4-5", "max_tokens": 40 + len(texts) * 20,
            "system": system, "messages": [{"role": "user", "content": user}]}


def disambiguate_brand_batch(texts: list, brand_name: str, sphere: str = "") -> list:
    """Level-2 brand-lane filter: True = off-topic homonym (hide). Default-keep,
    fail-open: all False on no-key/error."""
    n = len(texts)
    if n == 0:
        return []
    if not LLM_API_KEY:
        return [False] * n

    import httpx

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=_build_disambiguate_payload(texts, brand_name, sphere),
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
            log.warning("disambiguate_brand_batch failed: %s", e)
            return [False] * n

    flags = [False] * n
    try:
        for obj in data:
            i = obj.get("i")
            if isinstance(i, int) and 0 <= i < n:
                flags[i] = bool(obj.get("is_offtopic"))
    except Exception:
        return [False] * n
    return flags


def classify_ads_batch(texts: list, sphere: str = "") -> list:
    """Level-2 — Claude sphere-aware relevance filter (NOISE vs RELEVANT), one batched
    call. Returns list[bool] (is_ad=True means noise) aligned to input. Fail-open: all
    False on no-key/error."""
    n = len(texts)
    if n == 0:
        return []
    if not LLM_API_KEY:
        return [False] * n

    import httpx

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=_build_ads_classify_payload(texts, sphere),
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
