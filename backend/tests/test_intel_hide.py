"""Tests for soft-hide (спам убирает пост из ленты И сюжетов) и проброс
reply_to_tg_id через realtime-путь (иначе реплаи не определяются)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


# ── realtime проставляет reply_to_tg_id ──────────────────────────────────────

def test_store_realtime_sets_reply_to_tg_id():
    from radar.intel import seed, realtime
    from radar.intel.models import IntelMention

    s = _sess()
    seed.ensure_default_directions(s)
    s.commit()

    post = SimpleNamespace(
        platform="telegram", post_id="@chat/5", author="@user",
        text="по данным с места — удар по складу боеприпасов под Суджей",
        created_at=datetime.now(timezone.utc), views=0, url=None,
        reply_to_tg_id="4",
    )
    stored = realtime.store_realtime_post(s, post, side="ru", kind="chat",
                                          lexicon_terms=["удар"])
    assert stored is True
    s.commit()
    m = s.query(IntelMention).filter_by(post_id="@chat/5").one()
    assert m.reply_to_tg_id == "4", "realtime must carry reply_to_tg_id for is_reply"


# ── soft-hide исключает пост из story_detail и декремент post_count ───────────

def test_hidden_mention_excluded_from_story_detail():
    from radar.intel import seed, aggregate
    from radar.intel.models import (IntelMention, IntelIncident, IntelStory,
                                     IntelDirection)

    s = _sess()
    seed.ensure_default_directions(s)
    d = s.query(IntelDirection).first()
    now = datetime.now(timezone.utc)
    story = IntelStory(direction_id=d.id, title="t", first_seen_at=now,
                       last_seen_at=now, post_count=2)
    s.add(story); s.flush()
    inc = IntelIncident(direction_id=d.id, story_id=story.id,
                        first_seen_at=now, last_seen_at=now)
    s.add(inc); s.flush()
    keep = IntelMention(direction_id=d.id, platform="telegram", post_id="a",
                        author="@x", side="ru", text="видимый", created_at=now,
                        incident_id=inc.id)
    drop = IntelMention(direction_id=d.id, platform="telegram", post_id="b",
                        author="@y", side="ru", text="спам", created_at=now,
                        incident_id=inc.id, hidden=True)
    s.add_all([keep, drop]); s.commit()

    detail = aggregate.story_detail(s, story)
    texts = [e["text"] for e in detail["events"]]
    assert "видимый" in texts
    assert "спам" not in texts, "hidden mention must not appear in story detail"


# window signala ogranichivaet story_detail svezhimi postami

def test_story_detail_window_bounds_events_and_sources():
    """Opened from a signal, story_detail must show only posts inside the burst
    window."""
    from datetime import timedelta
    from radar.intel import seed, aggregate
    from radar.intel.models import (IntelMention, IntelIncident, IntelStory,
                                     IntelDirection)
    s = _sess()
    seed.ensure_default_directions(s)
    d = s.query(IntelDirection).first()
    now = datetime(2026, 6, 20, 15, 0)
    old = now - timedelta(days=1)
    story = IntelStory(direction_id=d.id, title="t", first_seen_at=old,
                       last_seen_at=now, post_count=2)
    s.add(story); s.flush()
    inc = IntelIncident(direction_id=d.id, story_id=story.id,
                        first_seen_at=old, last_seen_at=now)
    s.add(inc); s.flush()
    fresh = IntelMention(direction_id=d.id, platform="telegram", post_id="fresh",
                         author="@fresh", side="ru", text="fresh", created_at=now,
                         incident_id=inc.id)
    stale = IntelMention(direction_id=d.id, platform="telegram", post_id="stale",
                         author="@stale", side="ru", text="stale", created_at=old,
                         incident_id=inc.id)
    s.add_all([fresh, stale]); s.commit()
    since = now - timedelta(hours=1)
    detail = aggregate.story_detail(s, story, since=since, until=now)
    texts = [e["text"] for e in detail["events"]]
    assert "fresh" in texts
    assert "stale" not in texts
    src_names = {x["name"] for x in detail["sources"]}
    assert "@fresh" in src_names and "@stale" not in src_names
    assert detail["window"] is not None
    full = aggregate.story_detail(s, story)
    assert {"fresh", "stale"} <= {e["text"] for e in full["events"]}
    assert full["window"] is None


# ── realtime дропает дословный дубль примера-спама ──────────────────────────

def test_store_realtime_drops_exact_spam_example():
    from radar.intel import seed, realtime
    from radar.intel.models import IntelMention

    s = _sess()
    seed.ensure_default_directions(s)
    s.commit()

    spam_text = "по данным с места — удар по складу боеприпасов под Суджей"
    post = SimpleNamespace(
        platform="telegram", post_id="@chat/9", author="@user",
        text="  ПО ДАННЫМ с места — удар по складу боеприпасов под Суджей  ",
        created_at=datetime.now(timezone.utc), views=0, url=None, reply_to_tg_id=None,
    )
    stored = realtime.store_realtime_post(
        s, post, side="ru", kind="chat", lexicon_terms=["удар"],
        spam_words=[], spam_examples=[spam_text],
    )
    assert stored is False, "exact spam-example dupe must be dropped before storing"
    assert s.query(IntelMention).filter_by(post_id="@chat/9").first() is None


# ── удаление сюжета прячет упоминания и убирает сам сюжет ────────────────────

def test_delete_story_hides_mentions_and_removes_story():
    from radar.intel import seed
    from radar.intel.api import intel_story_delete
    from radar.intel.models import (IntelMention, IntelIncident, IntelStory,
                                     IntelStoryPoint, IntelDirection)

    s = _sess()
    seed.ensure_default_directions(s)
    d = s.query(IntelDirection).first()
    now = datetime.now(timezone.utc)
    story = IntelStory(direction_id=d.id, title="мусор", first_seen_at=now,
                       last_seen_at=now, post_count=1)
    s.add(story); s.flush()
    s.add(IntelStoryPoint(story_id=story.id, bucket_start=now,
                          mention_count=1, source_count=1))
    inc = IntelIncident(direction_id=d.id, story_id=story.id,
                        first_seen_at=now, last_seen_at=now)
    s.add(inc); s.flush()
    m = IntelMention(direction_id=d.id, platform="telegram", post_id="z",
                     author="@x", side="ru", text="спам-пост", created_at=now,
                     incident_id=inc.id)
    s.add(m); s.commit()
    sid = story.id

    res = intel_story_delete(sid, session=s, user=None)
    assert res["deleted"] is True
    assert res["hidden_mentions"] == 1
    assert s.get(IntelStory, sid) is None
    assert s.query(IntelStoryPoint).filter_by(story_id=sid).count() == 0
    assert s.query(IntelMention).filter_by(post_id="z").one().hidden is True
