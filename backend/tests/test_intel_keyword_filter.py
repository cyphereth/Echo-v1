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


# ── 3. keyword_or_geo_relevant unit tests ─────────────────────────────────────

def test_keyword_or_geo_relevant():
    from radar.intel.collector import keyword_or_geo_relevant

    # geo match (no lexicon needed)
    assert keyword_or_geo_relevant("бои под Суджей", []) is True

    # lexicon match (no geo)
    assert keyword_or_geo_relevant("выпустили калибр", ["калибр"]) is True

    # no match → dropped
    assert keyword_or_geo_relevant("обычная погода завтра", ["калибр"]) is False

    # term must match at word boundary — embedded substring should not match
    assert keyword_or_geo_relevant("некалибрный шуруп", ["калибр"]) is False

    # multi-word term works
    assert keyword_or_geo_relevant("попал storm shadow точно в цель", ["storm shadow"]) is True
