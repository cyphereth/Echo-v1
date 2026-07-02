"""Telegram source discovery for Intel.

Provides automatic TG chat/channel search via:
  1. contacts.SearchRequest — keyword search (underheard, neighbours, ЖК, schools…)
  2. GetChannelRecommendationsRequest — 1-hop graph traversal from found channels
  3. GetFullChannelRequest — linked discussion groups of found channels

Called from POST /intel/discover API endpoint.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from sqlalchemy.orm import Session

from .models import IntelDirection, IntelProbe
from ..core.providers.telegram import TelegramProvider, TelegramFloodWait

log = logging.getLogger(__name__)

# ── Search query templates ────────────────────────────────────────────────────
# {city} is replaced with the search city name (e.g. "Белгород")
_DISCOVERY_QUERIES = [
    "подслушано {city}",
    "прослушано {city}",
    "соседи {city}",
    "жк {city}",
    "аварии {city}",
    "новости {city}",
]

# Extra queries only for primary city (not for every satellite town)
_DISCOVERY_EXTRA_QUERIES = [
    "школа {city}",
    "дтп {city}",
    "сводки {city}",
    "воен {city}",
    "погода {city}",
    "вода {city}",
]

# Cities to use as search anchors per direction key.
# First entry = primary city, rest = additional search cities.
_DIRECTION_CITIES: dict[str, list[str]] = {
    "bryansk":          ["брянск", "новозыбков", "клинцы", "унеча", "сельцо", "дятьково", "карачев"],
    "belgorod":         ["белгород", "шебекино", "валуйки", "старый оскол", "губкин", "новый оскол", "бирюч"],
    "kursk":            ["курск", "суджа", "рыльск", "льгов", "обоянь", "фатеж", "щигры"],
    "voronezh":         ["воронеж", "лиски", "россошь", "богучар", "острогожск"],
    "oryol":            ["орёл", "мценск", "ливны", "болхов", "дмитровск"],
    "rostov":           ["ростов", "таганрог", "шахты", "волгодонск", "батайск", "новошахтинск", "каменск-шахтинский"],
    "crimea":           ["симферополь", "севастополь", "крым", "ялта", "керчь", "феодосия", "евпатория"],
    "krasnodar":        ["краснодар", "сочи", "новороссийск", "армавир", "тында"],
    "smolensk":         ["смоленск", "вязьма", "рославль", "сафоново"],
    "pskov":            ["псков", "великие луки", "остров"],
    "moscow":           ["москва"],
    "dnr":              ["донецк", "мариуполь", "горловка", "макеевка", "славянск", "енакиево", "волноваха"],
    "lnr":              ["луганск", "алчевск", "северодонецк", "лисичанск", "сватово"],
    "kyiv":             ["киев"],
    "kharkiv":          ["харьков", "изюм", "купянск", "балаклея", "чугуев"],
    "kherson":          ["херсон", "геническ", "скадовск", "новая каховка"],
    "zaporizhzhia":     ["запорожье", "мелитополь", "бердянск", "энергодар", "токмак"],
    "dnipropetrovsk":   ["днепр", "кривой рог", "каменское", "никополь", "синельниково", "павлоград"],
    "odesa":            ["одесса", "измаил", "илличёвск", "белгород-днестровский"],
    "mykolaiv":         ["николаев", "вознесенск", "первомайск"],
    "chernihiv":        ["чернигов", "новгород-северский", "прилуки", "нивки"],
    "sumy":             ["сумы", "шостка", "конотоп", "ромны", "охтирка"],
}

# Default side per direction key.
_DIRECTION_SIDE: dict[str, str] = {
    "bryansk": "ru", "belgorod": "ru", "kursk": "ru", "voronezh": "ru",
    "oryol": "ru", "rostov": "ru", "crimea": "ru", "krasnodar": "ru",
    "smolensk": "ru", "pskov": "ru", "moscow": "ru",
    "dnr": "ru", "lnr": "ru",
    "kyiv": "ua", "kharkiv": "ua", "kherson": "ua", "zaporizhzhia": "ua",
    "dnipropetrovsk": "ua", "odesa": "ua", "mykolaiv": "ua",
    "chernihiv": "ua", "sumy": "ua",
}

_MIN_PARTICIPANTS = 50
_MAX_CANDIDATES = 60
_MAX_RECOMMENDATIONS_PER_SEED = 15


# ── Internal helpers ──────────────────────────────────────────────────────────

# Patterns for channel/chat titles that are clearly not useful OSINT sources.
_JUNK_RE = re.compile(
    r"^(bot|sticker|emoji|gif|memes?|юмор|смешн|прикол|мемы|анекдот"
    r"|test|тест|бесплатн|реклам|promo|shop|store|купит|продаж"
    r"|music|музык|кино|film|фильм|игр|game|casino|казино|ставк)",
    re.IGNORECASE | re.UNICODE,
)


def _is_junk_title(title: str) -> bool:
    """Heuristic: True if the title looks like a non-useful bot/sticker/promo channel."""
    if len(title.strip()) < 2:
        return True
    return bool(_JUNK_RE.search(title))


def _discover_by_search(
    provider: TelegramProvider,
    city: str,
    direction_key: str,
    *,
    is_primary: bool = False,
) -> list[dict]:
    """Run contacts.SearchRequest for query templates against one city.

    Primary cities get extra queries (schools, military, etc.).
    Satellite towns only get the core set (underheard, neighbours, ЖК, etc.).

    Returns deduplicated candidate dicts.
    """
    candidates: dict[str, dict] = {}
    queries = list(_DISCOVERY_QUERIES)
    if is_primary:
        queries += _DISCOVERY_EXTRA_QUERIES

    for tmpl in queries:
        q = tmpl.format(city=city)
        try:
            results = provider.discover_channels(q, limit=20)
        except TelegramFloodWait as exc:
            log.warning("discover_channels(%r) flood wait %ds", q, exc.seconds)
            time.sleep(min(exc.seconds + 1, 60))
            continue
        except Exception as exc:
            log.warning("discover_channels(%r) failed: %s", q, exc)
            continue

        # Small backoff between requests to stay under TG rate limits
        time.sleep(0.5)

        for r in results:
            handle = r.get("handle", "")
            if not handle or not handle.startswith("@"):
                continue
            if r.get("participants", 0) < _MIN_PARTICIPANTS:
                continue
            title = r.get("title", "")
            if _is_junk_title(title):
                continue
            # Dedup by handle
            if handle not in candidates:
                candidates[handle] = {
                    "handle": handle,
                    "title": title,
                    "participants": r.get("participants", 0),
                    "kind": "channel",
                    "source": "search",
                    "direction": direction_key,
                    "subject": city.capitalize(),
                }

    return list(candidates.values())


def _expand_recommendations(
    provider: TelegramProvider,
    seeds: list[str],
    direction_key: str,
    subject: str,
    existing: set[str],
) -> list[dict]:
    """1-hop graph expansion: GetChannelRecommendationsRequest from seed channels.

    Only returns handles not already in *existing*.
    """
    candidates: list[dict] = []

    for seed in seeds[:30]:  # cap seeds to avoid flood
        try:
            recs = provider.channel_recommendations(seed, limit=_MAX_RECOMMENDATIONS_PER_SEED)
        except TelegramFloodWait as exc:
            log.warning("channel_recommendations(%s) flood wait %ds", seed, exc.seconds)
            time.sleep(min(exc.seconds + 1, 60))
            continue
        except Exception as exc:
            log.warning("channel_recommendations(%s) failed: %s", seed, exc)
            continue

        time.sleep(1.0)  # backoff between recommendation calls

        for rec in recs:
            handle = rec if isinstance(rec, str) else rec.get("handle", "")
            if not handle or not handle.startswith("@"):
                continue
            if handle in existing:
                continue
            existing.add(handle)

            # Resolve title/participants
            title = ""
            participants = 0
            try:
                ent = provider._await(provider._client.get_entity(handle))
                title = getattr(ent, "title", "") or ""
                participants = int(getattr(ent, "participants_count", 0) or 0)
            except Exception:
                pass

            if participants < _MIN_PARTICIPANTS:
                continue
            if _is_junk_title(title):
                continue

            candidates.append({
                "handle": handle,
                "title": title,
                "participants": participants,
                "kind": "channel",
                "source": "recommendation",
                "direction": direction_key,
                "subject": subject,
            })

    return candidates


def _expand_linked_chats(
    provider: TelegramProvider,
    channels: list[str],
    direction_key: str,
    subject: str,
    existing: set[str],
) -> list[dict]:
    """For each channel, check if it has a linked discussion group."""

    candidates: list[dict] = []

    for ch in channels[:20]:  # cap to avoid flood
        try:
            linked = provider.linked_chat(ch)
        except TelegramFloodWait as exc:
            log.warning("linked_chat(%s) flood wait %ds", ch, exc.seconds)
            time.sleep(min(exc.seconds + 1, 60))
            continue
        except Exception as exc:
            log.warning("linked_chat(%s) failed: %s", ch, exc)
            continue

        time.sleep(1.0)  # backoff between linked chat calls

        if not linked:
            continue

        handle = linked.get("handle")
        if not handle or not handle.startswith("@"):
            # Private linked chat — skip (would need chat_linked kind)
            continue
        if handle in existing:
            continue
        if linked.get("participants", 0) < _MIN_PARTICIPANTS:
            continue

        existing.add(handle)
        candidates.append({
            "handle": handle,
            "title": linked.get("title", ""),
            "participants": linked.get("participants", 0),
            "kind": "chat",
            "source": "linked",
            "direction": direction_key,
            "subject": subject,
        })

    return candidates


# ── Public API ────────────────────────────────────────────────────────────────

def discover_for_direction(
    direction_key: str,
    tg_provider: TelegramProvider,
    session: Session,
) -> list[dict]:
    """Main discovery function. Finds TG channels/chats for a given direction.

    Steps:
      1. Search by keyword templates for each city in the direction
      2. 1-hop graph expansion (recommendations) from found channels
      3. Linked discussion groups from found channels
      4. Filter out already-existing probes, junk, and small groups
    """
    cities = _DIRECTION_CITIES.get(direction_key)
    if not cities:
        raise ValueError(f"No discovery cities configured for direction '{direction_key}'")

    # Existing probe handles to exclude
    existing_handles = {
        row.query.strip().lower()
        for row in session.query(IntelProbe.query).filter(
            IntelProbe.platform == "telegram",
            IntelProbe.query.isnot(None),
        ).all()
        if row.query and row.query.strip().startswith("@")
    }

    all_candidates: list[dict] = []
    seen_handles: set[str] = set(existing_handles)
    search_channels: list[str] = []  # channels found via search (for recommendation expansion)
    flood_count = 0  # track consecutive flood waits — abort early if TG is throttling us
    subject = cities[0].capitalize()

    # Step 1: Search by keyword templates per city
    # Limit to first 3 cities to reduce TG API pressure
    for city in cities[:3]:
        found = _discover_by_search(tg_provider, city, direction_key, is_primary=(city == cities[0]))
        if len(found) == 0:
            flood_count += 1
            if flood_count >= 2:
                log.warning("Discovery: %d consecutive cities returned 0 results (flood wait?), stopping search early", flood_count)
                break
        else:
            flood_count = 0
        for c in found:
            h = c["handle"].lower()
            if h not in seen_handles:
                seen_handles.add(h)
                all_candidates.append(c)
                search_channels.append(c["handle"])

    if len(all_candidates) >= _MAX_CANDIDATES:
        return all_candidates[:_MAX_CANDIDATES]

    # Step 2: Graph expansion — recommendations from search results
    # Skip if search found nothing (likely flood wait)
    if search_channels:
        recs = _expand_recommendations(tg_provider, search_channels, direction_key, subject, seen_handles)
        for c in recs:
            all_candidates.append(c)
            search_channels.append(c["handle"])

    if len(all_candidates) >= _MAX_CANDIDATES:
        return all_candidates[:_MAX_CANDIDATES]

    # Step 3: Linked discussion groups
    linked = _expand_linked_chats(tg_provider, search_channels, direction_key, subject, seen_handles)
    for c in linked:
        all_candidates.append(c)

    # Sort by participants descending, cap
    all_candidates.sort(key=lambda c: -c.get("participants", 0))
    return all_candidates[:_MAX_CANDIDATES]


def default_side(direction_key: str) -> str:
    """Return the default 'side' for a direction (ru/ua)."""
    return _DIRECTION_SIDE.get(direction_key, "ru")


def available_directions() -> list[dict]:
    """Return list of directions that have discovery configured."""
    return [
        {"key": key, "cities": cities}
        for key, cities in _DIRECTION_CITIES.items()
    ]
