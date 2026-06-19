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


def _post(pid, text, author="@ch", created=None):
    from radar.core.providers.base import Post
    return Post(post_id=pid, platform="telegram", author=author, followers=5000,
                text=text, hashtags=[], created_at=created or datetime.now(timezone.utc),
                likes=1, views=10, comments=0, shares=0)


# ── scope_for_probe ────────────────────────────────────────────────────────────

def test_scope_for_probe_resolves_topic_and_brand():
    from radar.scope import scope_for_probe
    from radar.models import Brand, Topic, Probe
    s = _mem()
    s.add(Brand(id=1, name="B", keywords='["k"]', niche_keywords='["k"]'))
    s.add(Topic(id=1, name="T", keywords='["t"]', niche_keywords='["t"]'))
    s.flush()
    pb = Probe(brand_id=1, platform="telegram", kind="global", query="q")
    pt = Probe(topic_id=1, platform="telegram", kind="global", query="q")
    s.add_all([pb, pt]); s.flush()
    assert scope_for_probe(s, pb).kind == "brand"
    sc = scope_for_probe(s, pt)
    assert sc.kind == "topic" and sc.id == 1


# ── collect_probe topic branch ──────────────────────────────────────────────────

class _FakeTG:
    """Minimal SearchProvider: one page of posts, no cursor."""
    def __init__(self, posts): self.posts = posts
    def search(self, query, kind, cursor=None, platform="telegram"):
        from radar.core.providers.base import SearchPage
        return SearchPage(posts=self.posts, next_cursor=None)


def test_collect_probe_topic_stores_relevant_filters_offtopic():
    import radar.collector as C
    from radar.models import Topic, Probe, Mention
    s = _mem()
    s.add(Topic(id=1, name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция"]'))
    s.flush()
    probe = Probe(topic_id=1, platform="telegram", kind="global", query="инфляция", source="niche")
    s.add(probe); s.flush()
    prov = _FakeTG([
        _post("c/1", "Инфляция в России ускорилась"),   # on-topic → stored
        _post("c/2", "Погода завтра солнечная"),         # off-topic → skip
    ])
    n = C.collect_probe(s, probe, prov)
    assert n == 1
    rows = s.query(Mention).filter(Mention.topic_id == 1).all()
    assert len(rows) == 1
    assert rows[0].source == "niche" and rows[0].brand_id is None
    assert "Инфляция" in rows[0].text


def test_collect_probe_channel_trusts_source_skips_term_gate():
    """A kind="channel" probe is an already-discovered on-topic source, so its
    posts are NOT re-filtered by per-post keyword match (real news rarely repeats
    the narrow niche terms). Empty/too-short posts are still skipped."""
    import radar.collector as C
    from radar.models import Topic, Probe, Mention
    s = _mem()
    s.add(Topic(id=1, name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция"]'))
    s.flush()
    probe = Probe(topic_id=1, platform="telegram", kind="channel", query="@banksta", source="niche")
    s.add(probe); s.flush()
    prov = _FakeTG([
        _post("b/1", "JPMorgan и Goldman Sachs закрыли офисы для китайских сотрудников"),  # no term → still kept
        _post("b/2", ""),  # empty → skipped
    ])
    n = C.collect_probe(s, probe, prov)
    assert n == 1
    rows = s.query(Mention).filter(Mention.topic_id == 1).all()
    assert len(rows) == 1 and "JPMorgan" in rows[0].text


def test_collect_probe_respects_watermark():
    import radar.collector as C
    from radar.models import Topic, Probe, Mention
    s = _mem()
    s.add(Topic(id=1, name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция"]'))
    s.flush()
    probe = Probe(topic_id=1, platform="telegram", kind="global", query="инфляция",
                  source="niche", watermark="c/1")
    s.add(probe); s.flush()
    prov = _FakeTG([
        _post("c/2", "Инфляция в России снова ускорилась по данным Росстата"),  # new → stored
        _post("c/1", "Инфляция была стабильной весь прошлый год по отчёту"),    # == watermark
    ])
    n = C.collect_probe(s, probe, prov)
    assert n == 1  # stops at the watermark before processing c/1
    assert s.query(Mention).filter(Mention.topic_id == 1).count() == 1


# NB: ensure_topic_channels_discovered (hybrid seed/graph/LLM-gate) is covered in
# test_news_sources.py.


# ── ensure_topic_global_probe ───────────────────────────────────────────────────

def test_ensure_topic_global_probe_idempotent():
    import radar.collector as C
    from radar.models import Topic, Probe
    s = _mem()
    s.add(Topic(id=1, name="Экономика", keywords='["инфляция","рубль"]', niche_keywords='["инфляция"]'))
    s.flush()
    C.ensure_topic_global_probe(s, s.get(Topic, 1))
    C.ensure_topic_global_probe(s, s.get(Topic, 1))
    probes = s.query(Probe).filter(Probe.topic_id == 1, Probe.kind == "global").all()
    assert len(probes) == 1
    assert "инфляция" in probes[0].query


# ── scheduler topic TG pass ─────────────────────────────────────────────────────
# NOTE: test_run_topic_tg_pass_iterates_autocollect_topics,
# test_run_topic_tg_pass_caps_and_rotates_channels, and
# test_run_topic_tg_pass_aborts_on_floodwait are ported to test_news_passes.py
# (which tests radar.news.passes.run_topic_tg_pass against NewsTopic models).

def test_run_topic_tg_pass_noop_without_provider(monkeypatch):
    """Scheduler _run_topic_tg_pass is a no-op when no TG provider configured."""
    import radar.core.scheduler as SCH
    from radar.news.models import NewsTopic
    from radar.news.models import Base as NewsBase
    from radar.models import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    NewsBase.metadata.create_all(eng)
    s = _S(eng)
    s.add(NewsTopic(id=1, name="Экономика", auto_collect=True,
                    keywords='["инфляция"]', niche_keywords='["инфляция"]'))
    s.flush(); s.commit()
    called = []
    monkeypatch.setattr("radar.news.passes.ensure_topic_global_probe",
                        lambda sess, t: called.append(t.id))
    SCH._run_topic_tg_pass(s, tg_provider=None)
    assert called == []


# ── anti-flood hardening ────────────────────────────────────────────────────────

def test_telegram_floodwait_is_runtimeerror():
    from radar.core.providers.telegram import TelegramFloodWait
    e = TelegramFloodWait(42)
    assert isinstance(e, RuntimeError)
    assert e.seconds == 42 and "42" in str(e)
