from __future__ import annotations
import json, logging, os, re
from datetime import datetime, timezone, timedelta
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .models import Brand, Mention, MentionSnapshot, Probe
from .providers.base import Post, SearchProvider
from .spam import looks_like_ad_cheap

log = logging.getLogger(__name__)

VIRAL_VIEWS  = 500_000  # views above this = viral (post passes filters regardless)
VIRAL_LIKES  = 1_500    # smaller RU market: 1.5k likes already means a post took off
MIN_TEXT_LEN = 20       # posts/comments shorter than this are noise ("огонь", "👍")
MIN_FOLLOWERS = 100     # accounts below this are hidden unless the post went viral

def _now(): return datetime.now(timezone.utc)

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
    """For RU-market brands keep Russian Cyrillic posts only. Ukrainian/Kazakh
    (also Cyrillic) are excluded by their distinctive letters; foreign-language
    posts are kept only when viral."""
    if getattr(brand, "market", "global") != "ru":
        return True
    text = post.text or ""
    if any(ch in _NON_RU_CYRILLIC for ch in text):
        return False                      # Ukrainian/Kazakh — wrong geo, drop always
    if _is_viral(post):
        return True
    clean = " ".join(w for w in text.split() if not w.startswith("#"))
    return bool(re.search(r"[а-яёА-ЯЁ]", clean))

def _matches(post: Post, brand: Brand, probe: Probe) -> bool:
    text_lower = post.text.lower()
    exclusions = [e.lower() for e in brand.exclusions_list()]
    if any(exc in text_lower for exc in exclusions):
        return False

    if not _passes_language(post, brand):
        return False

    # Channel-monitoring probes (Telegram @channels the user explicitly chose to
    # watch): the channel itself is the relevance signal, so keep every post —
    # don't require a brand/competitor keyword in the text.
    if getattr(probe, "kind", None) == "channel":
        return True

    # Note: ad/spam/length/hashtag checks are NOT a hard drop anymore — matched
    # posts are stored with is_spam=True (store-but-hide) in collect_probe.

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
    # exact hashtag (not substring) — reduces false positives on ambiguous names.
    needle = (probe.label or probe.query).lower().lstrip("#")
    post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]

    def _hit(term: str) -> bool:
        term = term.lower().lstrip("#")
        if not term:
            return False
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text_lower):
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

def _upsert_mention(session: Session, post: Post, brand_id: int) -> Mention:
    stmt = (
        sqlite_insert(Mention).values(
            brand_id=brand_id, platform=post.platform, post_id=post.post_id,
            author=post.author, followers=post.followers, text=post.text,
            hashtags=json.dumps(post.hashtags), sound_id=post.sound_id,
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
    return session.query(Mention).filter_by(platform=post.platform, post_id=post.post_id).one()

def collect_probe(session: Session, probe: Probe, provider: SearchProvider) -> int:
    brand = session.get(Brand, probe.brand_id)
    if not brand: return 0
    new_watermark = None
    count         = 0
    cursor        = None
    found_watermark = False
    try:
        while not found_watermark:
            page = provider.search(probe.query, probe.kind, cursor, probe.platform)
            if not page.posts: break
            for post in page.posts:
                if new_watermark is None:
                    new_watermark = post.post_id
                if probe.watermark and post.post_id == probe.watermark:
                    found_watermark = True; break
                if not _matches(post, brand, probe): continue
                age = (_now().replace(tzinfo=None) - post.created_at.replace(tzinfo=None)).days
                if age > 7: continue
                # Cheap ad/spam rules + tiny-account floor → store-but-hide.
                spam = looks_like_ad_cheap(post.text, post.author, post.hashtags) \
                    or _below_follower_floor(post, getattr(brand, "local_mode", False))
                mention = _upsert_mention(session, post, brand.id)
                mention.source = probe.source
                mention.competitor = probe.label if probe.source == "competitor" else None
                mention.is_spam = spam
                if spam:
                    continue  # stored hidden; no snapshot, doesn't count toward pipeline volume
                session.add(MentionSnapshot(
                    mention_id=mention.id, ts=_now(),
                    likes=post.likes, views=post.views,
                    comments=post.comments, shares=post.shares,
                ))
                count += 1
            if page.next_cursor is None: break
            cursor = page.next_cursor
        if new_watermark:
            probe.watermark = new_watermark
        probe.next_run_at = _now()
        session.commit()
    except Exception:
        session.rollback()
        log.exception("Probe %s failed — watermark NOT moved", probe.id)
        raise
    return count


def collect_geo(session: Session, brand: Brand, provider: SearchProvider) -> int:
    """Best-effort: pull IG posts geotagged in the brand's city and store as niche.
    Fail-open — never raises into the main collect."""
    city = (getattr(brand, "geo", "") or "").strip()
    if not city:
        return 0
    # Topical terms: a geotagged post is only relevant if it's about the brand's
    # niche/category/sphere — otherwise location_posts is just "random city content".
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
            spam = looks_like_ad_cheap(post.text, post.author, post.hashtags) \
                or _below_follower_floor(post, local)
            clean = " ".join(w for w in post.text.split() if not w.startswith("#")).strip()
            if len(clean) < MIN_TEXT_LEN and not spam:
                spam = True
            # Off-topic city content (museums, cars, sport) → hide. In local_mode
            # relevance is decided later by client/provider persona (a real
            # client's lifestyle post won't contain a literal niche word).
            if not spam and not local and not _on_topic(post.text):
                spam = True
            mention = _upsert_mention(session, post, brand.id)
            mention.source = "niche"
            mention.is_spam = spam
            if spam:
                continue
            session.add(MentionSnapshot(
                mention_id=mention.id, ts=_now(),
                likes=post.likes, views=post.views,
                comments=post.comments, shares=post.shares,
            ))
            count += 1
        session.commit()
    except Exception:
        session.rollback()
        log.warning("collect_geo failed for brand %s city %r", brand.id, city)
    return count


# Sphere-NEUTRAL recommendation-intent search phrases — surface "asking for a
# recommendation" messages in ANY vertical (food, e-commerce, services, travel…).
# The brand's own niche_keywords add the domain specificity at search time.
UNIVERSAL_INTENT_TERMS = ["посоветуйте", "подскажите", "что выбрать", "какой лучше", "стоит ли"]
MAX_CHATS_PER_RUN      = int(os.getenv("MAX_CHATS_PER_RUN", "15"))


def _term_hit(text: str, terms: list[str]) -> bool:
    """Whole-word match — so "кафе" hits "Вьетнамское кафе" but NOT "кафедральный".
    Plain substring matching let a cathedral chat through the restaurant filter."""
    t = (text or "").lower()
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", t)
               for term in terms if term)


def _brand_terms(brand: Brand) -> list[str]:
    """The brand's domain vocabulary (niche + category keywords + meaningful sphere
    words) used to judge sphere-relevance — sphere-agnostic, from the brand's config."""
    terms = [t.lower() for t in (brand.niche_keywords_list() + brand.category_terms_list())]
    terms += [w.lower() for w in (getattr(brand, "sphere", "") or "").split() if len(w) > 3]
    return [t for t in dict.fromkeys(terms) if t]


MAX_DISCOVERY_CHANNELS = int(os.getenv("MAX_DISCOVERY_CHANNELS", "60"))


def ensure_chats_discovered(session: Session, brand: Brand, provider,
                            min_chats: int = 8, max_add: int = 40) -> int:
    """Auto-discover food/niche discussion chats by GROWING A GRAPH from the brand's
    already-curated channels (brand.tg_channels): expand them with Telegram's
    "similar channels" recommendations, then take each channel's linked discussion
    group — that's where the audience actually asks "куда сходить?". Far higher
    signal than blind keyword search. No-op once enough chats exist. Fail-open."""
    if not (hasattr(provider, "linked_chat") and hasattr(provider, "channel_recommendations")):
        return 0
    existing = (session.query(Probe)
                .filter(Probe.brand_id == brand.id, Probe.platform == "telegram",
                        Probe.kind.in_(("chat", "chat_linked"))).all())
    if len(existing) >= min_chats:
        return 0

    seeds = list(brand.tg_channels_list())
    # Bootstrap seed channels ONLY for brands that have curated NONE: search Telegram for
    # channels in the brand's sphere/niche/geo. Sphere-agnostic — works for a restaurant,
    # an online shop, a clinic, etc. (queries come from the brand's own config). Brands
    # with even a few curated channels grow purely from their own graph (cleaner seeds).
    if not seeds and hasattr(provider, "discover_channels"):
        geo     = (getattr(brand, "geo", "") or "").strip()
        sphere  = (getattr(brand, "sphere", "") or "").strip()
        queries = [f"{kw} {geo}".strip() for kw in brand.niche_keywords_list()[:3]]
        if sphere:
            queries.append(f"{sphere} {geo}".strip())
        # contacts.Search is fuzzy (e.g. "ресторан Брянск" can return a cathedral) —
        # keep only channels whose TITLE actually mentions the brand's domain.
        terms = _brand_terms(brand)
        for q in dict.fromkeys(x for x in queries if x):
            try:
                for c in provider.discover_channels(q, limit=20):
                    if _term_hit(c.get("title", ""), terms):
                        seeds.append(c["handle"])
            except Exception:
                log.warning("discover_channels failed for %r", q)
        seeds = list(dict.fromkeys(seeds))
    if not seeds:
        return 0  # nothing to grow from (no channels, no sphere/niche to search)

    # 1 hop of "similar channels" off each seed → a wider on-topic channel set.
    channels = list(seeds)
    for s in seeds:
        try:
            channels += provider.channel_recommendations(s, limit=10)
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
        # Public-username group → address it directly. Otherwise reach it through its
        # parent channel (kind="chat_linked", query = parent handle).
        if linked.get("handle"):
            kind, key = "chat", linked["handle"]
        elif linked.get("id") and linked.get("via"):
            kind, key = "chat_linked", linked["via"]
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        session.add(Probe(
            brand_id=brand.id, platform="telegram", kind=kind,
            query=key, source="niche", label=(linked["title"] or "")[:120],
            next_run_at=_now(), interval_sec=3600,
        ))
        added += 1
    session.commit()
    return added


def collect_chats(session: Session, brand: Brand, provider) -> int:
    """Monitor public group chats as a niche source: search each discovered chat
    (stored as kind="chat" probes) for the brand's niche terms + generic intent
    phrases, and store matching messages as niche mentions. Intent questions get
    flagged as opportunities downstream by the pipeline. Fail-open per chat."""
    if not hasattr(provider, "search_chat"):
        return 0  # provider doesn't support chat search (TikHub/SocialCrawl)
    # Least-recently-run first so a brand with more chats than MAX_CHATS_PER_RUN
    # rotates through all of them across successive runs instead of starving the tail.
    chats = (
        session.query(Probe)
        .filter(Probe.brand_id == brand.id, Probe.platform == "telegram",
                Probe.kind.in_(("chat", "chat_linked")))
        .order_by(Probe.next_run_at.asc())
        .limit(MAX_CHATS_PER_RUN)
        .all()
    )
    if not chats:
        return 0

    from .pipeline import _looks_like_intent
    terms = _brand_terms(brand)
    # Search the brand's top niche keywords (domain) + sphere-neutral intent phrases.
    search_terms = list(dict.fromkeys(brand.niche_keywords_list()[:3] + UNIVERSAL_INTENT_TERMS))

    def _topical(text: str) -> bool:
        return _term_hit(text, terms)

    count = 0
    for probe in chats:
        handle = probe.query
        # username group → search_chat; username-less linked group → resolve via parent.
        if probe.kind == "chat_linked":
            _search = lambda t: provider.search_linked_chat(handle, t, limit=20)
        else:
            _search = lambda t: provider.search_chat(handle, t, limit=20)
        seen: set[str] = set()
        try:
            for term in search_terms:
                for post in _search(term):
                    if post.post_id in seen:
                        continue
                    seen.add(post.post_id)
                    clean = " ".join(w for w in post.text.split() if not w.startswith("#")).strip()
                    spam = looks_like_ad_cheap(post.text, post.author, post.hashtags) \
                        or len(clean) < MIN_TEXT_LEN
                    # Keep only on-topic or recommendation-intent messages — a busy chat
                    # is full of "ага"/"спасибо" noise we don't want as mentions.
                    if not spam and not (_topical(post.text) or _looks_like_intent(post.text)):
                        spam = True
                    mention = _upsert_mention(session, post, brand.id)
                    mention.source = "niche"
                    mention.is_spam = spam
                    if spam:
                        continue
                    session.add(MentionSnapshot(
                        mention_id=mention.id, ts=_now(),
                        likes=post.likes, views=post.views,
                        comments=post.comments, shares=post.shares,
                    ))
                    count += 1
            session.commit()
        except Exception:
            session.rollback()
            log.warning("collect_chats failed for brand %s chat %s", brand.id, handle)
        # Move this chat to the back of the rotation regardless of outcome.
        probe.next_run_at = _now() + timedelta(seconds=probe.interval_sec or 3600)
        session.commit()
    return count
