# backend/tests/test_intel_stories.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_update_stories_clusters_and_verifies():
    from radar.intel.models import IntelDirection, IntelMention, IntelStory
    from radar.intel import stories
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    now = datetime.now(timezone.utc)
    for i, author in enumerate(["@a", "@b", "@c"]):
        s.add(IntelMention(direction_id=d.id, platform="tg", post_id=f"p{i}", author=author,
                           side="ru", text="удар по складу под Суджей сегодня", created_at=now))
    s.commit()
    stories.update_stories(s, d.id, embed=lambda txt: [float(len(txt))])
    st = s.query(IntelStory).first()
    assert st is not None
    assert st.source_count == 3
    assert st.verified is True


def test_update_stories_splits_by_subject():
    """Verbatim alerts about DIFFERENT cities in one oblast must not collapse into one
    story — the subject guard keeps them apart (regression for «Шостка»+«Воронеж»)."""
    from radar.intel.models import IntelDirection, IntelMention, IntelStory
    from radar.intel import stories
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    now = datetime.now(timezone.utc)
    txt = "угроза применения бпла, перейдите в укрытие"  # identical text → identical embed
    rows = [("@a", "Суджа"), ("@b", "Суджа"), ("@c", "Льгов")]
    for i, (author, subj) in enumerate(rows):
        s.add(IntelMention(direction_id=d.id, platform="tg", post_id=f"p{i}", author=author,
                           side="ru", text=txt, subject=subj, created_at=now))
    s.commit()
    # constant embedding → without the guard all three would be one story
    stories.update_stories(s, d.id, embed=lambda txt: [1.0])
    subjects = sorted(st.subject for st in s.query(IntelStory).all())
    assert subjects == ["Льгов", "Суджа"]  # two distinct stories, one per city


def test_update_stories_none_subject_does_not_join_city():
    """A post with no locality forms its own bucket and never merges into a city story."""
    from radar.intel.models import IntelDirection, IntelMention, IntelStory
    from radar.intel import stories
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    now = datetime.now(timezone.utc)
    txt = "угроза применения бпла, перейдите в укрытие"
    s.add(IntelMention(direction_id=d.id, platform="tg", post_id="p0", author="@a",
                       side="ru", text=txt, subject="Суджа", created_at=now))
    s.add(IntelMention(direction_id=d.id, platform="tg", post_id="p1", author="@b",
                       side="ru", text=txt, subject=None, created_at=now))
    s.commit()
    stories.update_stories(s, d.id, embed=lambda txt: [1.0])
    assert s.query(IntelStory).count() == 2
