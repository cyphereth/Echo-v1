"""Brand-domain probe collector.

Lifts the BRAND branch of radar/collector.py::collect_probe and reparameterizes it
against BrandProbe / BrandMention / BrandMentionSnapshot.  No Scope, no topic path.
"""
from __future__ import annotations
import hashlib, json, logging, os, re
from functools import lru_cache
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .models import Brand, BrandMention, BrandMentionSnapshot, BrandProbe
from ..core.providers.base import Post, SearchProvider
from ..core.spam import looks_like_ad_cheap

# Same env-var as legacy radar/collector.py so freshness discipline is shared.
NICHE_FRESH_HOURS = int(os.getenv("NICHE_FRESH_HOURS", "24"))
MIN_TEXT_LEN = 20

log = logging.getLogger(__name__)

VIRAL_VIEWS   = 500_000
VIRAL_LIKES   = 1_500
MIN_FOLLOWERS = 100

# Russian morphology — lets domain terms match inflected forms ("ресторане",
# "ресторанов" → "ресторан"). pymorphy3 is the Py3.11+ fork (pymorphy2 needs the
# removed pkg_resources); fall back to exact matching if neither is importable.
def _load_morph():
    for mod in ("pymorphy2", "pymorphy3"):
        try:
            return __import__(mod).MorphAnalyzer()
        except Exception:
            continue
    log.info("pymorphy not available — term matching falls back to exact word match")
    return None

_MORPH   = _load_morph()
_WORD_RE = re.compile(r"\w+", re.UNICODE)

@lru_cache(maxsize=50_000)
def _lemma(word: str) -> str:
    if _MORPH is None:
        return word
    try:
        return _MORPH.parse(word)[0].normal_form
    except Exception:
        return word

def _lemmas(text: str) -> set[str]:
    return {_lemma(w) for w in _WORD_RE.findall(text.lower())}

def _now(): return datetime.now(timezone.utc)

def _word_in(text: str, term: str) -> bool:
    """Whole-word (boundary) match of `term` within `text` (both already lowercased)."""
    if not term:
        return False
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))

def _is_viral(post: Post) -> bool:
    return (post.likes or 0) >= VIRAL_LIKES or (post.views or 0) >= VIRAL_VIEWS

def _below_follower_floor(post: Post, local_mode: bool = False) -> bool:
    """Tiny account (0 < followers < 100) whose post didn't go viral. followers==0
    means 'unknown' (no data) — not penalized. In local_mode the floor is off:
    ordinary city residents (few followers) ARE the local audience."""
    if local_mode:
        return False
    f = post.followers or 0
    return 0 < f < MIN_FOLLOWERS and not _is_viral(post)

# Letters unique to Ukrainian (і ї є ґ) or Kazakh (ә ғ қ ң ө ұ ү һ і) — never used
# in Russian. Their presence means the post is NOT Russian-market, even though it's
# Cyrillic. Geo is geo: a viral Ukrainian/Kazakh post is still the wrong country.
_NON_RU_CYRILLIC = set("іїєґІЇЄҐәғқңөұүһəҒҚҢӨҰҮҺ")

def _passes_language(post: Post, brand: Brand) -> bool:
    """For RU-market brands keep Russian Cyrillic posts only."""
    if getattr(brand, "market", "global") != "ru":
        return True
    text = post.text or ""
    if any(ch in _NON_RU_CYRILLIC for ch in text):
        return False
    if _is_viral(post):
        return True
    clean = " ".join(w for w in text.split() if not w.startswith("#"))
    return bool(re.search(r"[а-яёА-ЯЁ]", clean))

def _matches(post: Post, brand: Brand, probe: BrandProbe) -> bool:
    text_lower = post.text.lower()
    exclusions = [e.lower() for e in brand.exclusions_list()]
    if any(exc in text_lower for exc in exclusions):
        return False

    if not _passes_language(post, brand):
        return False

    # Channel-monitoring probes (Telegram @channels the user explicitly chose to
    # watch): the channel itself is the relevance signal, so keep every post.
    if getattr(probe, "kind", None) == "channel":
        return True

    if probe.source == "brand":
        keywords      = [k.lower() for k in brand.keywords_list()]
        hashtags      = [h.lower().lstrip("#") for h in brand.hashtags_list()]
        post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]
        # Strip hashtags from text so keyword match requires mention in caption body.
        text_no_tags  = " ".join(w for w in post.text.split() if not w.startswith("#")).lower()
        return (
            any(kw in text_no_tags for kw in keywords) or
            any(ht in post_hashtags for ht in hashtags)
        )

    # competitor / niche: require the term as a whole word/phrase in text (word
    # boundaries avoid substring collisions like "вб" inside "обувь") OR as an
    # exact hashtag — reduces false positives on ambiguous names.
    needle = (probe.label or probe.query).lower().lstrip("#")
    post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]

    def _hit(term: str) -> bool:
        term = term.lower().lstrip("#")
        if not term:
            return False
        if _word_in(text_lower, term):
            return True
        return any(term == h or term in h for h in post_hashtags)

    if not _hit(needle):
        return False
    # Geo-appended probe (query carries a city beyond the label): require the
    # city too, so "макияж Казань" doesn't match generic Kazan city content.
    label = (probe.label or "").lower()
    query = (probe.query or "").lower()
    if label and query and query != label:
        city = query.replace(label, "").strip()
        if city and not _hit(city):
            return False
    return True


def _upsert_mention(session: Session, post: Post, brand_id: int, platform: str | None = None) -> BrandMention:
    plat = platform or getattr(post, "platform", "unknown")
    stmt = (
        sqlite_insert(BrandMention).values(
            brand_id=brand_id,
            platform=plat, post_id=post.post_id,
            author=post.author, followers=post.followers, text=post.text,
            hashtags=json.dumps(post.hashtags),
            sound_id=getattr(post, "sound_id", None),
            created_at=post.created_at, likes=post.likes, views=post.views,
            comments=post.comments, shares=post.shares, updated_at=_now(),
        ).on_conflict_do_update(
            index_elements=["platform", "post_id"],
            set_={
                "likes": post.likes, "views": post.views,
                "comments": post.comments, "shares": post.shares,
                "followers": post.followers, "updated_at": _now(),
            },
        )
    )
    session.execute(stmt)
    session.flush()
    return session.query(BrandMention).filter_by(platform=plat, post_id=post.post_id).one()


def collect_probe(session: Session, probe: BrandProbe, provider) -> int:
    """Collect posts for one BrandProbe.

    - Resolves the probe's Brand; returns 0 if brand was deleted.
    - Applies brand relevance gate (_matches: language + keyword/hashtag match).
    - Deduplicates on (platform, post_id) via UNIQUE constraint (upsert).
    - Applies follower floor + spam rules to ALL brand-scope probes (any source);
      stores spam as hidden (no snapshot).
    - Advances the probe watermark to the first post_id seen this run.
    - Returns the count of non-spam mentions stored this pass.
    """
    brand = session.get(Brand, probe.brand_id)
    if brand is None:
        return 0

    new_watermark   = None
    count           = 0
    cursor          = None
    found_watermark = False

    try:
        while not found_watermark:
            page = provider.search(probe.query, probe.kind, cursor)
            if not page.posts:
                break
            for post in page.posts:
                if new_watermark is None:
                    new_watermark = post.post_id
                if probe.watermark and post.post_id == probe.watermark:
                    found_watermark = True
                    break

                # Relevance gate: language + keyword/hashtag/channel match.
                if not _matches(post, brand, probe):
                    continue

                # Age gate (same as legacy collect_probe: 7-day window).
                age = (_now().replace(tzinfo=None) - post.created_at.replace(tzinfo=None)).days
                if age > 7:
                    continue

                # Cheap ad/spam rules + tiny-account floor (faithful to legacy: floor
                # applies to ALL brand-scope probes, regardless of source).
                spam = looks_like_ad_cheap(post.text, post.author, post.hashtags)
                spam = spam or _below_follower_floor(post, getattr(brand, "local_mode", False))

                mention = _upsert_mention(session, post, brand.id, platform=probe.platform)
                mention.source     = probe.source
                mention.competitor = probe.label if probe.source == "competitor" else None
                mention.is_spam    = spam
                if spam:
                    continue  # stored hidden; no snapshot, doesn't count toward pipeline volume

                session.add(BrandMentionSnapshot(
                    mention_id=mention.id, ts=_now(),
                    likes=post.likes, views=post.views,
                    comments=post.comments, shares=post.shares,
                ))
                count += 1

            next_cursor = getattr(page, "next_cursor", None) or getattr(page, "cursor", None)
            if next_cursor is None:
                break
            cursor = next_cursor

        if new_watermark:
            probe.watermark = new_watermark
        probe.next_run_at = _now()
        session.commit()

    except Exception:
        session.rollback()
        log.exception("BrandProbe %s failed — watermark NOT moved", probe.id)
        raise

    return count


# ---------------------------------------------------------------------------
# Brand-native web collector — writes BrandMention (NOT legacy Mention)
# ---------------------------------------------------------------------------

def _web_query_terms(name: str, keywords: list[str]) -> str:
    """Build a search query from brand name + first 5 niche keywords."""
    parts = [name] + keywords[:5]
    return " ".join(p for p in parts if p).strip() or name


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or "web"
    except Exception:
        return "web"


def _web_published(value) -> datetime:
    if value:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:len(fmt) + 2], fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return _now()


def _store_niche_brand_post(
    session: Session, brand_id: int, post: Post, spam: bool
) -> bool:
    """Upsert a niche-source web post as BrandMention.

    Mirrors legacy _store_niche_post:
    - Drops posts older than NICHE_FRESH_HOURS (freshness gate).
    - Stores spam hidden (no snapshot, returns False).
    - Returns True only when the post counts toward pipeline volume.
    """
    created = post.created_at.replace(tzinfo=None) if post.created_at.tzinfo else post.created_at
    if (_now().replace(tzinfo=None) - created) > timedelta(hours=NICHE_FRESH_HOURS):
        return False  # stale — skip
    mention = _upsert_mention(session, post, brand_id, platform="web")
    mention.source = "niche"
    mention.is_spam = spam
    if spam:
        return False
    session.add(BrandMentionSnapshot(
        mention_id=mention.id, ts=_now(),
        likes=post.likes, views=post.views,
        comments=post.comments, shares=post.shares,
    ))
    return True


# ---------------------------------------------------------------------------
# Brand-native geo + chat collectors — write BrandMention / BrandProbe
# ---------------------------------------------------------------------------

UNIVERSAL_INTENT_TERMS = ["посоветуйте", "подскажите", "что выбрать", "какой лучше", "стоит ли"]
MAX_CHATS_PER_RUN      = int(os.getenv("MAX_CHATS_PER_RUN", "15"))
MAX_DISCOVERY_CHANNELS = int(os.getenv("MAX_DISCOVERY_CHANNELS", "60"))


def _brand_terms(brand: Brand) -> list[str]:
    """Niche + category keywords + sphere words — used for sphere-relevance checks."""
    terms = [t.lower() for t in (brand.niche_keywords_list() + brand.category_terms_list())]
    terms += [w.lower() for w in (getattr(brand, "sphere", "") or "").split() if len(w) > 3]
    return [t for t in dict.fromkeys(terms) if t]


def collect_geo(session: Session, brand: Brand, provider) -> int:
    """Pull IG posts geotagged in the brand's city and store as BrandMention (niche).

    Brand-native port of legacy radar/collector.py::collect_geo.
    Writes BrandMention instead of Mention.  Fail-open — never raises.
    """
    city = (getattr(brand, "geo", "") or "").strip()
    if not city:
        return 0
    local = getattr(brand, "local_mode", False)
    terms = [t.lower() for t in (brand.niche_keywords_list() + brand.category_terms_list())]
    if local:
        terms += [t.lower() for t in brand.audience_terms_list()]
    sphere_words = [w.lower() for w in (getattr(brand, "sphere", "") or "").split() if len(w) > 3]

    def _on_topic(text: str) -> bool:
        t = text.lower()
        return any(term in t for term in terms) or any(w in t for w in sphere_words)

    count = 0
    try:
        posts = provider.fetch_location_posts(city, "instagram", limit=15)
        for post in posts:
            spam = (looks_like_ad_cheap(post.text, post.author, post.hashtags)
                    or _below_follower_floor(post, local))
            clean = " ".join(w for w in post.text.split() if not w.startswith("#")).strip()
            if len(clean) < MIN_TEXT_LEN and not spam:
                spam = True
            if not spam and not local and not _on_topic(post.text):
                spam = True
            if _store_niche_brand_post(session, brand.id, post, spam):
                count += 1
        session.commit()
    except Exception:
        session.rollback()
        log.warning("collect_geo failed for brand %s city %r", brand.id, city)
    return count


def ensure_chats_discovered(
    session: Session, brand: Brand, provider,
    min_chats: int = 8, max_add: int = 40
) -> int:
    """Auto-discover Telegram discussion chats and store as BrandProbe rows.

    Brand-native port of legacy radar/collector.py::ensure_chats_discovered.
    Uses BrandProbe instead of Probe.  Fail-open.
    """
    if not (hasattr(provider, "linked_chat") and hasattr(provider, "channel_recommendations")):
        return 0
    existing = (session.query(BrandProbe)
                .filter(BrandProbe.brand_id == brand.id, BrandProbe.platform == "telegram",
                        BrandProbe.kind.in_(("chat", "chat_linked"))).all())
    if len(existing) >= min_chats:
        return 0

    seeds = list(brand.tg_channels_list())
    if not seeds and hasattr(provider, "discover_channels"):
        geo    = (getattr(brand, "geo", "") or "").strip()
        sphere = (getattr(brand, "sphere", "") or "").strip()
        queries = [f"{kw} {geo}".strip() for kw in brand.niche_keywords_list()[:3]]
        if sphere:
            queries.append(f"{sphere} {geo}".strip())
        terms = _brand_terms(brand)
        for q in dict.fromkeys(x for x in queries if x):
            try:
                for c in provider.discover_channels(q, limit=20):
                    title = c.get("title", "")
                    if any(t in title.lower() for t in terms):
                        seeds.append(c["handle"])
            except Exception:
                log.warning("discover_channels failed for query %r", q)

    channels: list[str] = list(seeds)
    for s in seeds:
        try:
            for rec in provider.channel_recommendations(s, limit=20):
                channels.append(rec["handle"])
        except Exception:
            log.warning("channel_recommendations failed for %s", s)
    channels = list(dict.fromkeys(channels))[:MAX_DISCOVERY_CHANNELS]

    seen  = {p.query for p in existing}
    added = 0
    for ch in channels:
        if added >= max_add:
            break
        try:
            linked = provider.linked_chat(ch)
        except Exception:
            log.warning("linked_chat failed for %s", ch)
            continue
        if not linked:
            continue
        if linked.get("handle"):
            kind, key = "chat", linked["handle"]
        elif linked.get("id") and linked.get("via"):
            kind, key = "chat_linked", linked["via"]
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        session.add(BrandProbe(
            brand_id=brand.id, platform="telegram", kind=kind,
            query=key, source="niche", label=(linked["title"] or "")[:120],
            next_run_at=_now(), interval_sec=3600,
        ))
        added += 1
    session.commit()
    return added


def collect_chats(session: Session, brand: Brand, provider) -> int:
    """Monitor Telegram group chats and store matching messages as BrandMentions.

    Brand-native port of legacy radar/collector.py::collect_chats.
    Uses BrandProbe (kind='chat'/'chat_linked') and writes BrandMention.
    Fail-open per chat.
    """
    if not hasattr(provider, "search_chat"):
        return 0
    chats = (
        session.query(BrandProbe)
        .filter(BrandProbe.brand_id == brand.id, BrandProbe.platform == "telegram",
                BrandProbe.kind.in_(("chat", "chat_linked")))
        .order_by(BrandProbe.next_run_at.asc())
        .limit(MAX_CHATS_PER_RUN)
        .all()
    )
    if not chats:
        return 0

    from .pipeline import _looks_like_intent
    terms = _brand_terms(brand)
    search_terms = list(dict.fromkeys(brand.niche_keywords_list()[:3] + UNIVERSAL_INTENT_TERMS))

    def _topical(text: str) -> bool:
        t = text.lower()
        return any(term in t for term in terms)

    count = 0
    for probe in chats:
        handle = probe.query
        method = "search_linked_chat" if probe.kind == "chat_linked" else "search_chat"
        search = getattr(provider, method, None)
        if search is None:
            log.warning("collect_chats: provider has no %s — skipping %s", method, handle)
            continue
        wm = int(probe.watermark) if (probe.watermark or "").isdigit() else 0
        newest = wm
        seen_ids: set[str] = set()
        try:
            for term in search_terms:
                for post in search(handle, term, limit=20, min_id=wm):
                    try:
                        newest = max(newest, int(post.post_id))
                    except (ValueError, TypeError):
                        pass
                    if post.post_id in seen_ids:
                        continue
                    seen_ids.add(post.post_id)
                    clean = " ".join(w for w in post.text.split() if not w.startswith("#")).strip()
                    spam = (looks_like_ad_cheap(post.text, post.author, post.hashtags)
                            or len(clean) < MIN_TEXT_LEN)
                    if not spam and not (_topical(post.text) or _looks_like_intent(post.text)):
                        spam = True
                    if _store_niche_brand_post(session, brand.id, post, spam):
                        count += 1
            session.commit()
        except Exception:
            session.rollback()
            log.warning("collect_chats failed for brand %s chat %s", brand.id, handle)
        if newest > wm:
            probe.watermark = str(newest)
        probe.next_run_at = _now() + timedelta(seconds=probe.interval_sec or 3600)
    session.commit()
    return count


def collect_web(session: Session, brand: Brand, provider) -> int:
    """Search the web for the brand's topic and store relevant results as BrandMentions.

    Brand-native port of legacy radar/collector.py::collect_web.
    Writes BrandMention (NOT legacy Mention) so results are visible to the brand
    domain.  Faithful to legacy behaviour:
      - Relevance gate: niche_keywords term hit (no niche_keywords → keep all).
      - Freshness window: NICHE_FRESH_HOURS (default 24 h).
      - Dedup: (platform, post_id) UNIQUE where post_id = sha1(url)[:16].
      - Spam/follower floor: web posts have followers=0 (unknown) → floor skipped,
        spam=False (same as legacy which passed spam=False to _store_niche_post).
    Returns the count of relevant results stored this pass.
    """
    query = _web_query_terms(brand.name, brand.keywords_list())
    results = provider.search(query)
    terms = [t.lower() for t in brand.niche_keywords_list() if t]
    n = 0
    for r in results:
        url = r.get("url")
        if not url:
            continue
        text = f"{r.get('title', '')}. {r.get('content', '')}".strip()
        # Relevance gate: if niche terms exist, require at least one to hit.
        if terms and not any(t in text.lower() for t in terms):
            continue  # off-topic
        post = Post(
            post_id=hashlib.sha1(url.encode()).hexdigest()[:16],
            platform="web", author=_domain(url), followers=0,
            text=text, hashtags=[], created_at=_web_published(r.get("published")),
            likes=0, views=0, comments=0, shares=0,
        )
        if _store_niche_brand_post(session, brand.id, post, spam=False):
            n += 1
    session.commit()
    return n
