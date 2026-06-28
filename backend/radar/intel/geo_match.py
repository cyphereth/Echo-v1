"""Pure geo-text matcher for the intel feed.

Given a post's text and a mapping of direction_key → [lowercase terms],
return the set of direction_keys whose terms appear as whole words
(boundary-aware, Cyrillic-safe) in the text.

Boundary rule: a term matches when it is preceded by a non-letter and is
followed by either a non-letter OR by 1–3 trailing Cyrillic letters that
look like a Slavic inflectional ending (case grammatical suffixes: -е/-ой/
-у/-ом/-ській/-ська). Anything longer (e.g. "-овый") is treated as a
different word and rejected. This lets "брянск" match "брянске" / "брянской"
but not "брянсковый".
"""
from __future__ import annotations
import re

# Pre-boundary: the char before the term must NOT be a letter.
_BOUNDARY_BEFORE = r"(?<![A-Za-zА-Яа-яЄєІіЇїЎў])"
# Post-boundary: either a non-letter, OR up to 3 trailing letters then a non-letter.
# `(?=...)` lookahead so we don't consume the ending (lets us join alternations cleanly).
_INFLECTION_TAIL = r"[А-Яа-яЄєІіЇїЎў]{1,3}(?![А-Яа-яЄєІіЇїЎў])"
_BOUNDARY_AFTER = rf"(?:{_INFLECTION_TAIL}|(?![A-Za-zА-Яа-яЄєІіЇїЎў]))"


def _compile(terms):
    # Escape each term, wrap with boundary lookarounds, join with |.
    parts = [
        _BOUNDARY_BEFORE + re.escape(t.lower()) + _BOUNDARY_AFTER
        for t in terms
        if t and t.strip()
    ]
    if not parts:
        return None
    return re.compile("|".join(parts))


def match_directions(text, terms_by_key):
    """Return the set of direction keys whose terms appear in `text`.

    `terms_by_key` is `{direction_key: [term, ...]}` — all terms already
    lowercase (the caller lowercases; this function does not mutate).
    """
    if not text:
        return set()
    lowered = text.lower()
    matched = set()
    for key, terms in terms_by_key.items():
        rx = _compile(terms)
        if rx is not None and rx.search(lowered):
            matched.add(key)
    return matched

