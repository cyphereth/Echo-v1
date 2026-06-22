import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _probe(s):
    from radar.intel.models import IntelProbe
    p = IntelProbe(platform="telegram", kind="channel", query="https://t.me/x", side="ru")
    s.add(p); s.commit()
    return p


def test_channel_time_window_stops_at_old(monkeypatch):
    monkeypatch.setenv("INTEL_COLLECT_WINDOW_HOURS", "36")
    monkeypatch.setenv("MAX_POSTS_PER_SOURCE", "1000")
    import importlib, radar.intel.collector as C
    importlib.reload(C)
    from radar.intel import seed
    from radar.intel.models import IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    p = _probe(s)
    now = datetime.now(timezone.utc)
    # newest-first: 4 fresh, then older-than-window — collection must stop at the old one
    fresh = [SimpleNamespace(post_id=f"x/{i}", author="@x",
             text=f"свежий пост про обстрел под направлением номер {i} сегодня",
             followers=0, created_at=now - timedelta(hours=i), hashtags=[], likes=0) for i in range(4)]
    old = [SimpleNamespace(post_id=f"x/old{i}", author="@x",
           text=f"старый пост двухдневной давности номер {i} давно прошёл",
           followers=0, created_at=now - timedelta(hours=48 + i), hashtags=[], likes=0) for i in range(20)]
    prov = SimpleNamespace(search=lambda q, k, c: SimpleNamespace(posts=fresh + old, cursor=None, next_cursor=None))
    n = C.collect_probe(s, p, prov)
    assert s.query(IntelMention).count() == 4   # only the fresh ones
    assert n == 4


def test_channel_safety_cap(monkeypatch):
    monkeypatch.setenv("INTEL_COLLECT_WINDOW_HOURS", "999999")  # window effectively off
    monkeypatch.setenv("MAX_POSTS_PER_SOURCE", "10")
    import importlib, radar.intel.collector as C
    importlib.reload(C)
    from radar.intel import seed
    from radar.intel.models import IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    p = _probe(s)
    now = datetime.now(timezone.utc)
    posts = [SimpleNamespace(post_id=f"x/{i}", author="@x",
             text=f"длинный пост номер {i} про обстрел под направлением сегодня вечером",
             followers=0, created_at=now, hashtags=[], likes=0) for i in range(100)]
    prov = SimpleNamespace(search=lambda q, k, c: SimpleNamespace(posts=posts, cursor=None, next_cursor=None))
    n = C.collect_probe(s, p, prov)
    assert s.query(IntelMention).count() <= 10
    assert n <= 10
