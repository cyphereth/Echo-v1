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
