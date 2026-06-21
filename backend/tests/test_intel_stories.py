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
