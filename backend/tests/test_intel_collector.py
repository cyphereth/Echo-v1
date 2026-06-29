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


def test_collect_probe_writes_source_m2m_row():
    """A channel post that survives filtering gets an m2m row tagging its
    detected direction (source). Main collector flow + Feed-v2 m2m layer."""
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelMentionDirection, IntelLexicon
    s = _sess(); seed.ensure_default_directions(s)
    # lexicon term so keyword_relevant admits the post (geo match alone also works,
    # but we add a lexicon term to be robust to filter changes).
    s.add(IntelLexicon(term="обстановка", meaning="сводка", category="general")); s.commit()
    p = IntelProbe(platform="telegram", kind="channel", query="@mil", side="ru"); s.add(p); s.commit()
    post = SimpleNamespace(post_id="@mil/1", author="@mil", text="обстановка в курске сегодня спокойная",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=[post], cursor=None))
    n = collector.collect_probe(s, p, prov)
    assert n == 1
    rows = s.query(IntelMentionDirection).all()
    # The mention's detected direction is tagged as 'source' in m2m.
    m = s.query(IntelMention).one()
    assert any(r.mention_id == m.id and r.match_type == "source" for r in rows)


def test_collect_probe_writes_geo_m2m_row_for_text_mention():
    """A post whose text mentions multiple regions gets m2m rows for each.
    Probe subscribed direction is the source; other geo matches get 'geo'."""
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelMentionDirection, IntelLexicon
    s = _sess(); seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="обстрел", meaning="обстрел", category="events")); s.commit()
    p = IntelProbe(platform="telegram", kind="channel", query="@ua", side="ua"); s.add(p); s.commit()
    # Post mentions both Брянск and Харьков — both seeded with geo_terms.
    post = SimpleNamespace(post_id="@ua/9", author="@ua",
                           text="зафіксовано обстріл під Брянськом, також дані по харькову",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=[post], cursor=None))
    n = collector.collect_probe(s, p, prov)
    assert n == 1
    m2m = {(r.direction_id, r.match_type) for r in s.query(IntelMentionDirection).all()}
    # Both bryansk and kharkiv direction_ids should appear in m2m.
    # The detected primary direction is tagged 'source'; any other geo match 'geo'.
    from radar.intel.models import IntelDirection
    bryansk = s.query(IntelDirection).filter_by(key="bryansk").first()
    kharkiv = s.query(IntelDirection).filter_by(key="kharkiv").first()
    # Both directions must be linked (one as source, the other as geo — order depends on detect_direction).
    keys_linked = {r.direction_id for r in s.query(IntelMentionDirection).all()}
    assert bryansk.id in keys_linked
    assert kharkiv.id in keys_linked
    # Exactly one is 'source' (the detected primary), the other is 'geo'.
    assert any(mt == "source" for _, mt in m2m)
    assert any(mt == "geo" for _, mt in m2m)
