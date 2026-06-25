"""Lightweight Ukrainian → Russian translation for intel posts.

Detection: Ukrainian-specific characters (і, ї, є, ґ) are absent in Russian.
If the text contains enough of them it's treated as Ukrainian and translated.
Uses deep_translator.GoogleTranslator (free, no API key).
Failures are silent — callers get the original text back.
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger(__name__)

# Ukrainian-exclusive letters (not present in Russian alphabet)
_UA_CHARS = re.compile(r"[іїєґІЇЄҐ]")
_UA_THRESHOLD = 2  # at least N Ukrainian-exclusive chars → treat as Ukrainian


def _is_ukrainian(text: str) -> bool:
    return len(_UA_CHARS.findall(text)) >= _UA_THRESHOLD


_translator = None


def _get_translator():
    global _translator
    if _translator is None:
        try:
            from deep_translator import GoogleTranslator
            _translator = GoogleTranslator(source="uk", target="ru")
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
