import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _topic(s, name="Экономика", kws='["инфляция"]'):
    from radar.models import Topic
    t = Topic(id=1, name=name, kind="default", keywords=kws, niche_keywords=kws)
    s.add(t); s.flush()
    return t


class _Prov:
    """discover_channels + channel_recommendations stub."""
    def __init__(self, discover=None, recs=None):
        self._discover = discover or {}
        self._recs = recs or {}
    def discover_channels(self, query, limit=30):
        return self._discover.get(query, [])
    def channel_recommendations(self, handle, limit=10):
        return self._recs.get(handle, [])


# ── Block 1: hybrid discovery ───────────────────────────────────────────────────

def test_seed_channels_added_without_gate(monkeypatch):
    """Default-topic seeds are added as channel probes, no LLM gate."""
    import radar.collector as C
    from radar.models import Probe
    monkeypatch.setattr("radar.seed.TOPIC_SEED_CHANNELS", {"Экономика": ["@rbc_news", "@tass_agency"]})
    # gate must NOT be consulted for seeds
    monkeypatch.setattr(C, "classify_source", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gate called on seed")))
    s = _mem(); t = _topic(s)
    added = C.ensure_topic_channels_discovered(s, t, _Prov())
    probes = {p.query for p in s.query(Probe).filter(Probe.kind == "channel")}
    assert probes == {"@rbc_news", "@tass_agency"}
    assert added == 2


def test_recommendations_off_seeds_are_trusted(monkeypatch):
    """With seeds present but below min_chan, similar-channels off seeds are added."""
    import radar.collector as C
    from radar.models import Probe
    monkeypatch.setattr("radar.seed.TOPIC_SEED_CHANNELS", {"Экономика": ["@rbc_news"]})
    s = _mem(); t = _topic(s)
    prov = _Prov(recs={"@rbc_news": ["@interfax", "@tass_agency"]})
    C.ensure_topic_channels_discovered(s, t, prov, min_chan=6)
    probes = {p.query for p in s.query(Probe).filter(Probe.kind == "channel")}
    assert probes == {"@rbc_news", "@interfax", "@tass_agency"}


def test_keyword_discovery_is_llm_gated_for_seedless_topics(monkeypatch):
    """A topic with no seeds falls back to keyword discovery, gated by classify_source."""
    import radar.collector as C
    from radar.models import Probe
    monkeypatch.setattr("radar.seed.TOPIC_SEED_CHANNELS", {})   # no seeds for any topic
    s = _mem(); t = _topic(s, name="Крипта", kws='["биткоин"]')
    prov = _Prov(discover={"биткоин": [
        {"handle": "@btc_news", "title": "Биткоин Новости"},
        {"handle": "@crypto_pump", "title": "Сигналы памп закрытый клуб"},
    ]})
    monkeypatch.setattr(C, "classify_source",
                        lambda title, topic: "Новости" in title)   # keep only real news
    C.ensure_topic_channels_discovered(s, t, prov)
    probes = {p.query for p in s.query(Probe).filter(Probe.kind == "channel")}
    assert probes == {"@btc_news"}


def test_classify_source_falls_back_to_term_hit_without_llm(monkeypatch):
    import radar.collector as C
    from radar.models import Topic
    s = _mem(); t = _topic(s)
    import radar.llm as llm
    def _no_key(*a, **k):
        raise llm.LLMNotConfigured("no key")
    monkeypatch.setattr(C.llm, "complete", _no_key)
    assert C.classify_source("Инфляция и экономика", t) is True
    assert C.classify_source("Котики каждый день", t) is False


def test_discovery_idempotent(monkeypatch):
    import radar.collector as C
    from radar.models import Probe
    monkeypatch.setattr("radar.seed.TOPIC_SEED_CHANNELS", {"Экономика": ["@rbc_news"]})
    s = _mem(); t = _topic(s)
    C.ensure_topic_channels_discovered(s, t, _Prov())
    added2 = C.ensure_topic_channels_discovered(s, t, _Prov())
    assert added2 == 0
    assert s.query(Probe).filter(Probe.kind == "channel").count() == 1


# ── Block 2: junk cleanup ───────────────────────────────────────────────────────

def test_purge_removes_nonseed_channels_and_mentions(monkeypatch):
    import radar.maintenance as M
    from radar.models import Probe, Mention
    monkeypatch.setattr("radar.seed.TOPIC_SEED_CHANNELS", {"Экономика": ["@rbc_news"]})
    s = _mem(); t = _topic(s)
    now = datetime.now(timezone.utc)
    s.add(Probe(topic_id=1, platform="telegram", kind="channel", query="@rbc_news", source="niche"))
    s.add(Probe(topic_id=1, platform="telegram", kind="channel", query="@junk_psy", source="niche"))
    s.add(Probe(topic_id=1, platform="telegram", kind="global", query="инфляция", source="niche"))
    s.flush()
    s.add(Mention(topic_id=1, platform="telegram", post_id="j1", author="@junk_psy",
                  text="мусор", source="niche", created_at=now))
    s.add(Mention(topic_id=1, platform="telegram", post_id="r1", author="@rbc_news",
                  text="новость", source="niche", created_at=now))
    s.commit()
    removed = M.purge_topic_sources(s, topic_id=1)
    chans = {p.query for p in s.query(Probe).filter(Probe.kind == "channel")}
    assert chans == {"@rbc_news"}                          # seed kept
    assert s.query(Probe).filter(Probe.kind == "global").count() == 1   # global kept
    assert s.query(Mention).filter_by(author="@junk_psy").count() == 0  # junk mentions gone
    assert s.query(Mention).filter_by(author="@rbc_news").count() == 1  # seed mentions kept
    assert removed == 1
