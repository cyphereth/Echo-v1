import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _brand1_scope(s):
    from radar.models import Brand
    from radar.scope import scope_for_brand
    b = s.get(Brand, 1)
    if b is None:
        b = Brand(id=1, name="TestBrand", keywords='[]', niche_keywords='[]')
        s.add(b); s.flush()
    return scope_for_brand(b)


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_report_model_persists():
    from radar.models import Report
    s = _mem()
    r = Report(brand_id=1, kind="digest", body="hello")
    s.add(r); s.commit()
    got = s.query(Report).one()
    assert got.kind == "digest" and got.body == "hello" and got.story_id is None
    assert got.created_at is not None


def _mk_story(s, title, post_count, anomaly=False, sent=0.0):
    from radar.models import Story, StoryPoint
    base = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)
    st = Story(brand_id=1, title=title, status="active", is_anomaly=anomaly,
               post_count=post_count, first_seen_at=base, last_seen_at=base)
    s.add(st); s.flush()
    s.add(StoryPoint(story_id=st.id, bucket_start=base, mention_count=post_count,
                     avg_sentiment=sent, source_count=2))
    s.flush()
    return st


def test_build_daily_digest_creates_report(monkeypatch):
    import radar.digests as D
    from radar.models import Report
    s = _mem()
    _mk_story(s, "кризис", 10, anomaly=True, sent=-0.6)
    _mk_story(s, "акция", 4, sent=0.3)
    s.commit()
    seen = {}
    def _fake_complete(system, user, max_tokens=1024, model=None):
        seen["user"] = user
        return "СВОДКА: всё под контролем."
    monkeypatch.setattr(D.llm, "complete", _fake_complete)

    report = D.build_daily_digest(s, _brand1_scope(s))
    assert report is not None
    assert report.kind == "digest"
    assert report.body == "СВОДКА: всё под контролем."
    assert s.query(Report).count() == 1
    assert "кризис" in seen["user"] and "акция" in seen["user"]
    assert "АНОМАЛИЯ" in seen["user"]


def test_build_daily_digest_none_when_no_stories(monkeypatch):
    import radar.digests as D
    s = _mem()
    monkeypatch.setattr(D.llm, "complete", lambda *a, **k: "x")
    assert D.build_daily_digest(s, _brand1_scope(s)) is None


def test_run_digest_pass_calls_builder_for_autocollect_brands(monkeypatch):
    import radar.scheduler as SCH
    from radar.models import Brand
    s = _mem()
    s.add(Brand(id=1, name="a", auto_collect=True))
    s.add(Brand(id=2, name="b", auto_collect=False))   # excluded
    s.add(Brand(id=3, name="c", auto_collect=True))
    s.commit()

    called = []
    monkeypatch.setattr("radar.digests.build_daily_digest",
                        lambda sess, scope: called.append(scope.id) or None)
    SCH._run_digest_pass(s)
    assert sorted(called) == [1, 3]
