"""Tests for the military-keyword relevance filter (JSON seed + channel gate).

Covers:
  1. ingest_lexicon_json — real keywords.seed.json round-trip + idempotency
  2. channel collect_probe — keyword gate drops general, keeps military
  3. keyword_or_geo_relevant — unit tests for the shared helper
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace

_SEED_PATH = os.path.join(
    os.path.dirname(__file__), "..", "radar", "intel", "data", "keywords.seed.json"
)


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa – registers IntelLexicon et al.
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


# ── 1. JSON lexicon ingest ────────────────────────────────────────────────────

def test_ingest_lexicon_json():
    """Ingest the real seed file; check counts, a known term, and idempotency."""
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon

    s = _sess()

    # First pass — ingest.  The seed has 461 word entries across 10 categories;
    # 37 terms appear in more than one category (duplicates → update on 2nd occurrence).
    # So: added (unique terms) + updated (dup re-occurrences) >= 400 total.
    result = ingest_lexicon_json(s, _SEED_PATH)
    assert result["added"] >= 400, f"expected >=400 added, got {result}"
    # added + updated == total word entries in file
    assert result["added"] + result["updated"] >= 400, f"unexpected counts: {result}"

    # DB row count == unique terms (dupes → single row per term)
    db_count = s.query(IntelLexicon).count()
    assert db_count >= 400, f"expected >=400 rows in DB, got {db_count}"
    assert db_count == result["added"], f"DB row count {db_count} != added {result['added']}"

    # Known terms must be present (lowercased) with a non-empty category
    for known in ("калибр", "shahed", "прилёт"):
        row = s.query(IntelLexicon).filter_by(term=known).first()
        assert row is not None, f"term '{known}' not found after ingest"
        assert row.category, f"term '{known}' has empty category"

    # Second pass — idempotent: added == 0, all rows updated
    result2 = ingest_lexicon_json(s, _SEED_PATH)
    assert result2["added"] == 0, f"expected 0 added on re-ingest, got {result2}"
    assert result2["updated"] >= 400


# ── 2. Channel probe: keyword gate drops general, keeps military ───────────────

def test_channel_keeps_military_drops_general():
    """collect_probe on a channel probe stores only the military-relevant post."""
    from radar.intel import seed, collector
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelProbe, IntelMention

    s = _sess()
    seed.ensure_default_directions(s)
    ingest_lexicon_json(s, _SEED_PATH)

    p = IntelProbe(platform="telegram", kind="channel", query="@testchannel", side="ua")
    s.add(p)
    s.commit()

    now = datetime.now(timezone.utc)

    # Two posts both long enough (>= MIN_TEXT_LEN) and within the time window.
    # Only the first matches a lexicon keyword; the second is pure general news.
    military_post = SimpleNamespace(
        post_id="@testchannel/1",
        author="@testchannel",
        text="ночью прилёт по складу, вторичная детонация в районе базы",
        followers=0,
        created_at=now,
        hashtags=[],
        likes=0,
    )
    general_post = SimpleNamespace(
        post_id="@testchannel/2",
        author="@testchannel",
        text="Президент возложил венок к мемориалу сегодня утром на центральной площади",
        followers=0,
        created_at=now,
        hashtags=[],
        likes=0,
    )

    page = SimpleNamespace(posts=[military_post, general_post], cursor=None)
    prov = SimpleNamespace(search=lambda q, k, c: page)

    n = collector.collect_probe(s, p, prov)

    assert n == 1, f"expected 1 stored mention, got {n}"
    stored = s.query(IntelMention).one()
    assert stored.post_id == "@testchannel/1", (
        f"wrong post stored: {stored.post_id!r}"
    )


# ── 2b. Curator positive keywords admit posts that miss the lexicon ────────────

def test_curator_keyword_admits_otherwise_dropped_post():
    """A post that fails the military lexicon is admitted if it matches a curator-managed
    positive keyword (kind="keyword"), OR'd into the gate."""
    from radar.intel import seed, collector
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelProbe, IntelMention, IntelSpam

    s = _sess()
    seed.ensure_default_directions(s)
    ingest_lexicon_json(s, _SEED_PATH)

    # Curator adds a non-military positive keyword.
    s.add(IntelSpam(kind="keyword", value="наводнение"))
    s.commit()

    p = IntelProbe(platform="telegram", kind="channel", query="@testchannel", side="ua")
    s.add(p)
    s.commit()

    now = datetime.now(timezone.utc)
    matches_keyword = SimpleNamespace(
        post_id="@testchannel/1", author="@testchannel",
        text="сильное наводнение затопило центральные улицы города сегодня утром",
        followers=0, created_at=now, hashtags=[], likes=0,
    )
    general = SimpleNamespace(
        post_id="@testchannel/2", author="@testchannel",
        text="Президент возложил венок к мемориалу сегодня утром на центральной площади",
        followers=0, created_at=now, hashtags=[], likes=0,
    )
    page = SimpleNamespace(posts=[matches_keyword, general], cursor=None)
    prov = SimpleNamespace(search=lambda q, k, c: page)

    n = collector.collect_probe(s, p, prov)
    assert n == 1, f"expected 1 stored mention, got {n}"
    stored = s.query(IntelMention).one()
    assert stored.post_id == "@testchannel/1"


def test_curator_keyword_overrides_length_gate_for_chat():
    """A short chat reply (< MIN_TEXT_LEN) matching a curator keyword is admitted —
    the keyword hit bypasses the length noise-gate (the reply bug)."""
    from radar.intel.collector import chat_message_relevant, MIN_TEXT_LEN

    short = "наводнение!"  # < 20 chars — would normally be dropped by the length gate
    assert len(short) < MIN_TEXT_LEN
    # Without the keyword → dropped (too short, no lexicon hit)
    assert chat_message_relevant(short, "@u", {}, []) is False
    # With the curator keyword → admitted despite being short
    assert chat_message_relevant(short, "@u", {}, ["наводнение"]) is True
    # Text with no alphabetic char is still dropped even on a keyword hit
    assert chat_message_relevant("123 456", "@u", {}, ["123"]) is False


def test_load_keywords_returns_only_keyword_kind():
    from radar.intel.models import IntelSpam
    from radar.intel.spam_filter import load_keywords

    s = _sess()
    s.add_all([
        IntelSpam(kind="keyword", value="Наводнение"),
        IntelSpam(kind="word", value="реклама"),
        IntelSpam(kind="example", value="купи сейчас"),
    ])
    s.commit()

    kws = load_keywords(s)
    assert kws == ["наводнение"], f"unexpected keywords: {kws}"


# ── 3. keyword_relevant unit tests (keyword-only, geo is NOT an admit path) ────

def test_keyword_relevant():
    from radar.intel.collector import keyword_relevant

    # geo-only text with NO lexicon term → dropped (geo no longer admits)
    assert keyword_relevant("бои под Суджей", {}) is False

    # lexicon match
    assert keyword_relevant("выпустили калибр", {"калибр": "strong"}) is True

    # no match → dropped
    assert keyword_relevant("обычная погода завтра", {"калибр": "strong"}) is False

    # term must match at word boundary — embedded substring should not match
    assert keyword_relevant("некалибрный шуруп", {"калибр": "strong"}) is False

    # multi-word term works
    assert keyword_relevant("попал storm shadow точно в цель", {"storm shadow": "strong"}) is True


def test_abbreviation_filter_case_sensitive():
    """Uppercase military abbreviations admit a post; their lowercase homographs don't."""
    from radar.intel.collector import keyword_relevant

    # uppercase abbreviations match even with an empty word-lexicon
    assert keyword_relevant("ночью работала ТА по переднему краю", {}) is True
    assert keyword_relevant("зафиксирован пуск ПКР по цели", {}) is True
    assert keyword_relevant("БПЛА над акваторией порта", {}) is True
    assert keyword_relevant("отработала РСЗО по позициям", {}) is True

    # lowercase "та" (pronoun) must NOT trigger — the whole reason for case-sensitivity
    assert keyword_relevant("та самая история повторяется снова и снова", {}) is False

    # abbreviation embedded in a longer uppercase token does not match (word boundary)
    assert keyword_relevant("колонна ВТА выдвинулась рано утром сегодня", {}) is False


def test_keyword_relevant_weather_stoplist():
    """Ambiguous weather words (град/смерч) are dropped only in a weather context."""
    from radar.intel.collector import keyword_relevant

    # ambiguous-only + weather context → dropped (false positive)
    assert keyword_relevant("прогноз погоды: ожидается град и гроза", {"град": "strong"}) is False
    assert keyword_relevant("в регионе прошёл смерч, синоптики предупреждают", {"смерч": "strong"}) is False

    # ambiguous term but NO weather context → kept (real military "Град")
    assert keyword_relevant("работает град по позициям противника", {"град": "strong"}) is True

    # ambiguous + weather context BUT also a non-ambiguous military term → kept
    assert keyword_relevant("несмотря на грозу, зафиксирован прилёт града", {"град": "strong", "прилёт": "strong"}) is True


def test_keyword_relevant_tier_rule():
    from radar.intel.collector import keyword_relevant
    strong_only = {"шахед": "strong"}
    weak_only   = {"сейчас": "weak", "работа": "weak"}

    # 1 strong → впуск
    assert keyword_relevant("летит шахед", strong_only) is True
    # 1 weak без гео → отбой
    assert keyword_relevant("прямо сейчас отвечу", weak_only) is False
    # 2 weak → впуск
    assert keyword_relevant("сейчас работа кипит", weak_only) is True
    # 1 weak + гео → впуск
    assert keyword_relevant("сейчас в Белгороде", weak_only, geo_hit=True) is True
    # 0 совпадений → отбой
    assert keyword_relevant("обычный текст", weak_only) is False


def test_keyword_relevant_weather_guard_kept():
    from radar.intel.collector import keyword_relevant
    lex = {"град": "strong"}
    # «град» в погодном контексте — не впуск даже как strong
    assert keyword_relevant("завтра ожидается град и гроза, прогноз погоды", lex) is False
    # «град» без погодного контекста — strong впуск
    assert keyword_relevant("по позициям отработал град", lex) is True


def test_matched_terms_returns_tiers():
    from radar.intel.collector import matched_terms
    out = matched_terms("выпустили калибр", {"калибр": "strong"})
    assert ("калибр", "strong") in out


def test_matched_terms_abbrev_is_strong():
    from radar.intel.collector import matched_terms
    out = matched_terms("замечен БПЛА над городом", {})
    assert ("БПЛА", "strong") in out


# ── 4. collect_probe: weak-only without geo is dropped ───────────────────────

def test_collect_probe_drops_single_weak(monkeypatch):
    from radar.intel import collector
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelMention, IntelProbe
    from radar.intel.seed import ensure_default_directions
    s = _sess()
    ensure_default_directions(s)
    ingest_lexicon_json(s, _SEED_PATH)

    probe = IntelProbe(query="@t", platform="telegram", side="ru",
                       kind="channel", watermark=None)
    s.add(probe); s.commit()

    def _post(pid, text):
        return SimpleNamespace(post_id=pid, text=text, author="a",
                               created_at=datetime.now(timezone.utc),
                               url=None, likes=0, reply_to_tg_id=None, media=None)

    # один weak («сейчас»), без гео и без второго weak-термина — должен отсеяться;
    # strong («прилёт») — пройти.
    page = SimpleNamespace(posts=[
        _post("1", "сейчас расскажу интересную новость про будущее экономики страны"),
        _post("2", "прилёт по складу, есть разрушения в районе базы"),
    ])

    prov = SimpleNamespace(
        search=lambda *a, **k: page,
        search_chat=lambda *a, **k: [],
    )

    collector.collect_probe(s, probe, prov)
    texts = [m.text for m in s.query(IntelMention).all()]
    assert any("прилёт" in t for t in texts), "strong post must be stored"
    assert not any("расскажу интересную" in t for t in texts), "single weak must be dropped"
