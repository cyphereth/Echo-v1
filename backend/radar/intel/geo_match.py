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
# Post-boundary: either a non-letter, OR up to 3 trailing letters that look
# like a Slavic inflectional ending (case grammatical suffixes: -е/-ой/-у/-ом/
# -ська/-ській). Anything longer (e.g. "-овый") is rejected. `(?=...)` lookahead
# so we don't consume the ending (lets us join alternations cleanly).
_INFLECTION_TAIL = r"[А-Яа-яЄєІіЇїЎў]{1,3}(?![А-Яа-яЄєІіЇїЎў])"
_BOUNDARY_AFTER = rf"(?:{_INFLECTION_TAIL}|(?![A-Za-zА-Яа-яЄєІіЇїЎў]))"


def _normalize_term(term):
    """Allow an optional soft sign 'ь' before the last letter, so that the
    Russian 'брянск' matches the Ukrainian 'брянськ' (and inflections like
    'брянськом'). Returns a regex pattern (string)."""
    if len(term) <= 1:
        return re.escape(term)
    head, last = term[:-1], term[-1]
    return re.escape(head) + r"ь?" + re.escape(last)


def _compile(terms):
    # Build one regex per term with boundary lookarounds + an optional ь before
    # the final letter (handles RU брянск ↔ UA брянськ) + a trailing inflection
    # tail (1-3 letters).
    parts = []
    for t in terms:
        t = (t or "").strip().lower()
        if not t:
            continue
        parts.append(_BOUNDARY_BEFORE + _normalize_term(t) + _BOUNDARY_AFTER)
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

