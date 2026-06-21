# backend/tests/test_intel_collect_tagging.py
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

def test_channel_post_tagged_by_geo():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelDirection
    s = _sess(); seed.ensure_default_directions(s)
    p = IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru"); s.add(p); s.commit()
    posts=[SimpleNamespace(post_id="@rybar/1", author="@rybar", text="удар по складу под Суджей",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    n=collector.collect_probe(s, p, prov)
    assert n==1
    m=s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "kursk"
    assert m.side == "ru"

def test_channel_post_without_geo_goes_unassigned():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelDirection
    s = _sess(); seed.ensure_default_directions(s)
    p = IntelProbe(platform="telegram", kind="channel", query="@x", side="ua"); s.add(p); s.commit()
    posts=[SimpleNamespace(post_id="@x/1", author="@x", text="общая сводка дня без географии тут",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    collector.collect_probe(s, p, prov)
    m=s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "unassigned"

def test_chat_noise_filter_drops_irrelevant_keeps_relevant():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    p = IntelProbe(platform="telegram", kind="chat", query="@chat", side="ru"); s.add(p); s.commit()
    msgs = [
        SimpleNamespace(post_id="@chat/1", author="u1", text="ок", followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0),  # noise (too short)
        SimpleNamespace(post_id="@chat/2", author="u2", text="прилёт под Суджей, вторичная детонация", followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0),  # relevant (geo)
    ]
    prov=SimpleNamespace(search_chat=lambda handle,term,limit=20,min_id=0: msgs)
    n=collector.collect_probe(s, p, prov)
    assert n==1
    assert s.query(IntelMention).one().post_id == "@chat/2"
