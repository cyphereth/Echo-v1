import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_rebuild_points_buckets_by_hour_and_counts_sources():
    from radar.intel import seed, stories
    from radar.intel.models import (
        IntelDirection, IntelStory, IntelIncident, IntelMention, IntelStoryPoint,
    )
    s = _sess()
    seed.ensure_default_directions(s)
    d = s.query(IntelDirection).first()
    st = IntelStory(direction_id=d.id, title="t",
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc))
    s.add(st); s.flush()
    inc = IntelIncident(direction_id=d.id, story_id=st.id, title="t",
                        first_seen_at=datetime.now(timezone.utc),
                        last_seen_at=datetime.now(timezone.utc))
    s.add(inc); s.flush()

    base = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)
    # hour 10:00 → 2 mentions from 2 distinct authors; hour 11:00 → 1 mention
    rows = [
        (base + timedelta(minutes=5),  "@a"),
        (base + timedelta(minutes=40), "@b"),
        (base + timedelta(hours=1, minutes=10), "@a"),
    ]
    for i, (ts, author) in enumerate(rows):
        s.add(IntelMention(direction_id=d.id, platform="telegram", post_id=f"p{i}",
                           author=author, side="ru", text="x", created_at=ts,
                           incident_id=inc.id))
    s.commit()

    stories.rebuild_points(s, d.id)

    pts = (s.query(IntelStoryPoint).filter_by(story_id=st.id)
           .order_by(IntelStoryPoint.bucket_start).all())
    assert len(pts) == 2, f"expected 2 hourly buckets, got {len(pts)}"
    assert pts[0].mention_count == 2 and pts[0].source_count == 2
    assert pts[1].mention_count == 1 and pts[1].source_count == 1


def test_rebuild_points_is_idempotent():
    from radar.intel import seed, stories
    from radar.intel.models import (
        IntelDirection, IntelStory, IntelIncident, IntelMention, IntelStoryPoint,
    )
    s = _sess()
    seed.ensure_default_directions(s)
    d = s.query(IntelDirection).first()
    st = IntelStory(direction_id=d.id, title="t",
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc))
    s.add(st); s.flush()
    inc = IntelIncident(direction_id=d.id, story_id=st.id, title="t",
                        first_seen_at=datetime.now(timezone.utc),
                        last_seen_at=datetime.now(timezone.utc))
    s.add(inc); s.flush()
    ts = datetime(2026, 6, 23, 9, 30, tzinfo=timezone.utc)
    s.add(IntelMention(direction_id=d.id, platform="telegram", post_id="p0",
                       author="@a", side="ru", text="x", created_at=ts, incident_id=inc.id))
    s.commit()

    stories.rebuild_points(s, d.id)
    stories.rebuild_points(s, d.id)   # second run must not duplicate
    assert s.query(IntelStoryPoint).filter_by(story_id=st.id).count() == 1
