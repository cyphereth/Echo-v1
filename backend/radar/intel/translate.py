"""Lightweight Ukrainian → Russian translation for intel posts.

Detection works on two signals:
  1. Ukrainian-exclusive letters (і, ї, є, ґ) — absent in Russian, so even ONE is a
     near-certain marker of Ukrainian.
  2. Ukrainian-specific marker words — for short posts that carry no special letters
     (e.g. «Загроза БпЛА. Суми»), where letter detection alone fails.

Translation uses deep_translator.GoogleTranslator with source="auto" so a post that
slips through but is actually Russian comes back unchanged (ru→ru), never corrupted.
Failures are silent — callers get the original text back.
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger(__name__)

# Ukrainian-exclusive letters (not present in the Russian alphabet) — any one is enough.
_UA_CHARS = re.compile(r"[іїєґІЇЄҐ]")

# Ukrainian-specific words with NO exclusive letters, common in air-alert / war posts.
# Each is non-Russian (RU equivalents differ: загроза≠угроза, вибух≠взрыв, ворог≠враг),
# so a single hit is a strong Ukrainian signal. Matched as whole words.
_UA_MARKERS = frozenset({
    "загроза", "загрози", "тривога", "тривоги", "укриття", "вибух", "вибухи",
    "негайно", "зараз", "дуже", "це", "був", "була", "було", "ворог", "ворога",
    "зброя", "ракетна", "ракетної", "повітряна", "повітряної", "щодо", "також",
    "після", "проти", "має", "залишайтеся", "перебувайте", "пролуна", "ппо",
})
_WORD_RE = re.compile(r"[а-яёіїєґ']+", re.IGNORECASE)


def _is_ukrainian(text: str) -> bool:
    if _UA_CHARS.search(text):
        return True
    words = {w.lower() for w in _WORD_RE.findall(text)}
    return bool(words & _UA_MARKERS)


_translator = None


def _get_translator():
    global _translator
    if _translator is None:
        try:
            from deep_translator import GoogleTranslator
            _translator = GoogleTranslator(source="auto", target="ru")
        except Exception as e:
            log.warning("deep_translator not available: %s", e)
    return _translator


def maybe_translate(text: str) -> str:
    """If text looks Ukrainian, return its Russian translation. Otherwise return as-is."""
    if not text or not _is_ukrainian(text):
        return text
    t = _get_translator()
    if t is None:
        return text
    try:
        result = t.translate(text)
        return result if result else text
    except Exception as e:
        log.debug("translation failed: %s", e)
        return text
