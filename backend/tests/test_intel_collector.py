# backend/tests/test_intel_collector.py
import os, sys
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

def test_collect_probe_writes_intel_mention_with_side():
    from radar.intel.models import IntelDirection, IntelProbe, IntelMention, IntelLexicon
    from radar.intel import collector
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    s.add(IntelLexicon(term="удар", meaning="strike", category="military"))
    p = IntelProbe(direction_id=d.id, platform="telegram", kind="channel", query="@mil", side="ru")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="@mil/1", author="@mil", text="удар по складу под Суджей сегодня",
                             followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=12)]
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, prov)
    assert n == 1
    m = s.query(IntelMention).one()
    assert m.side == "ru" and m.direction_id == d.id

def test_collect_probe_dedups_on_platform_post_id():
    from radar.intel.models import IntelDirection, IntelProbe, IntelMention, IntelLexicon
    from radar.intel import collector
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    s.add(IntelLexicon(term="удар", meaning="strike", category="military"))
    p = IntelProbe(direction_id=d.id, platform="telegram", kind="channel", query="@mil", side="ru")
    s.add(p); s.commit()
    post = SimpleNamespace(post_id="@mil/1", author="@mil", text="удар по складу под Суджей сегодня",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=[post], cursor=None))
    collector.collect_probe(s, p, prov)
    p.watermark = None
    n2 = collector.collect_probe(s, p, prov)
    assert n2 == 0
    assert s.query(IntelMention).count() == 1
