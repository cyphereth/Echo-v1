# backend/tests/test_intel_aggregate.py
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

def test_story_summary_shape_and_sides():
    from radar.intel.models import IntelDirection, IntelStory, IntelIncident, IntelMention
    from radar.intel import aggregate
    s = _sess()
    now = datetime.now(timezone.utc)
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    st = IntelStory(direction_id=d.id, title="Удар по складу", credibility="likely", verified=True,
                    source_count=3, post_count=5, first_seen_at=now, last_seen_at=now, summary="свод")
    s.add(st); s.flush()
    inc = IntelIncident(direction_id=d.id, story_id=st.id, title="i", post_count=5,
                        first_seen_at=now, last_seen_at=now); s.add(inc); s.flush()
    s.add(IntelMention(direction_id=d.id, platform="tg", post_id="p1", author="@a", side="ru",
                       text="x", created_at=now, incident_id=inc.id))
    s.add(IntelMention(direction_id=d.id, platform="tg", post_id="p2", author="@b", side="ua",
                       text="y", created_at=now, incident_id=inc.id))
    s.commit()
    out = aggregate.story_summary(s, st)
    assert out["id"] == st.id and out["direction"] == "kursk"
    assert set(out["sides"]) == {"ru", "ua"}
    for k in ("title","source_count","post_count","verified","credibility","spike_pct","sparkline","last_seen_at"):
        assert k in out

def test_compute_overview_keys():
    from radar.intel import aggregate
    s = _sess()
    out = aggregate.compute_overview(s, window_h=24)
    assert set(out.keys()) == {"kpis", "hot", "alerts", "top_stories"}
    assert set(out["kpis"].keys()) == {"events", "active_stories", "spiking_dirs"}
