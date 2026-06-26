"""Curator-managed spam filter for intel collection.

Two layers, applied to survivors of the relevance gate in collector.collect_probe:
  1. blocked_by_word — instant, free, deterministic stop-word match (no network).
  2. classify_spam_batch — Claude compares survivors against curator-supplied example
     junk posts in one batched call. Fail-open: drops nothing on no-key/error.

Both the stop-words and the examples live in the intel_spam table (IntelSpam).
"""
from __future__ import annotations

import json
import logging
import os
import re

from sqlalchemy.orm import Session

from .models import IntelSpam

log = logging.getLogger(__name__)

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")

# Cap how many example posts we ship as reference per classify call — keeps the
# prompt bounded as the curator's example list grows. Newest examples win.
MAX_EXAMPLES = 30


def load_spam(session: Session) -> tuple[list[str], list[str]]:
    """Return (blocklist_words, example_texts). Words lowercased; examples newest-first."""
    rows = session.query(IntelSpam).order_by(IntelSpam.id.desc()).all()
    words = [r.value.lower() for r in rows if r.kind == "word" and r.value]
    examples = [r.value for r in rows if r.kind == "example" and r.value]
    return words, examples[:MAX_EXAMPLES]


def blocked_by_word(text: str, blocklist) -> bool:
    """True if any stop-word/phrase appears in text at a word boundary, case-insensitive.

    Multi-word phrases are matched as a contiguous substring (still word-bounded at the
    ends). An empty blocklist never blocks.
    """
    low = (text or "").lower()
    if not low:
        return False
    for w in blocklist:
        w = (w or "").strip().lower()
        if not w:
            continue
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low):
            return True
    return False


def _norm(text: str) -> str:
    """Нормализуем текст для сравнения: схлопываем пробелы, lower, без краёв."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def is_exact_spam(text: str, examples) -> bool:
    """True, если text дословно (с точностью до регистра/пробелов) совпадает с одним
    из примеров-мусора куратора. Дешёво и детерминированно — без сети и без LLM."""
    n = _norm(text)
    if not n:
        return False
    return any(_norm(e) == n for e in (examples or []))


def is_spam_text(text: str, blocklist, examples) -> bool:
    """Единый дешёвый гейт для realtime-пути: стоп-слово ИЛИ дословный дубль примера.
    Не зовёт LLM (это делает только батч-путь поллера)."""
    return blocked_by_word(text, blocklist or []) or is_exact_spam(text, examples)


def classify_spam_batch(texts: list, examples: list) -> list:
    """Claude per text: is it the same kind of junk as the curator's examples?

    Returns list[bool] aligned to `texts` (True = spam → drop). Fail-open: returns
    all-False when there is no API key, no examples, or the call fails.
    """
    n = len(texts)
    if n == 0:
        return []
    if not LLM_API_KEY or not examples:
        return [False] * n

    import httpx

    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    ref = "\n".join(f"- {(e or '')[:200]}" for e in examples)
    system = (
        "Ты фильтр мусора для мониторинга. Куратор пометил приведённые ниже посты как "
        "НЕНУЖНЫЙ мусор (спам, реклама, оффтоп, флуд). Для каждого нового текста реши: "
        "это ТАКОЙ ЖЕ мусор, как в примерах куратора, — или нет. По умолчанию считай, "
        "что НЕ мусор; помечай спамом ТОЛЬКО при явном сходстве с примерами. "
        "Отвечай ТОЛЬКО валидным JSON."
    )
    user = (
        f"Примеры мусора от куратора:\n{ref}\n\n"
        f"Новые тексты:\n{numbered}\n\n"
        f'Верни JSON-массив по одному объекту на текст: '
        f'[{{"i":0,"is_spam":false}}, ...]. is_spam=true только для явного мусора.'
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
            log.warning("classify_spam_batch failed: %s", e)
            return [False] * n

    flags = [False] * n
    try:
        for obj in data:
            i = obj.get("i")
            if isinstance(i, int) and 0 <= i < n:
                flags[i] = bool(obj.get("is_spam"))
    except Exception:
        return [False] * n
    return flags
