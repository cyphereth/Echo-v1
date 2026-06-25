import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    import radar.intel.models  # register intel tables
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_intel_alert_roundtrip():
    from radar.intel.models import IntelAlert
    s = _mem()
    a = IntelAlert(scope="direction", direction_id=1, kind="direction_burst",
                   magnitude=320.0, title="Курское", message="Всплеск ×4")
    s.add(a); s.commit()
    got = s.query(IntelAlert).one()
    assert got.scope == "direction"
    assert got.kind == "direction_burst"
    assert got.acknowledged_at is None
    assert got.fired_at is not None


def test_emit_inserts_then_dedups_within_cooldown():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()

    first = alerts._emit(s, "direction", "direction_burst",
                         title="Курское", message="Всплеск ×4",
                         magnitude=300.0, direction_id=1)
    s.commit()
    assert first is not None
    assert s.query(IntelAlert).count() == 1

    # Same scope/ref/kind again → suppressed by cooldown.
    again = alerts._emit(s, "direction", "direction_burst",
                         title="Курское", message="Всплеск ×5",
                         magnitude=350.0, direction_id=1)
    s.commit()
    assert again is None
    assert s.query(IntelAlert).count() == 1


def test_emit_not_deduped_for_different_kind():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    alerts._emit(s, "story", "spike", title="t", message="m", magnitude=1.0, story_id=7)
    alerts._emit(s, "story", "source_influx", title="t", message="m", magnitude=1.0, story_id=7)
    s.commit()
    assert s.query(IntelAlert).count() == 2


def _direction(s, key="kursk", name="Курское"):
    from radar.intel.models import IntelDirection
    d = IntelDirection(key=key, name=name)
    s.add(d); s.flush()
    return d


def _anomalous_story(s, direction_id):
    """A story flagged is_anomaly with a spiking source-influx timeline."""
    from radar.intel.models import IntelStory, IntelStoryPoint
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    st = IntelStory(direction_id=direction_id, title="Прорыв обороны",
                    is_anomaly=True, post_count=12, source_count=5,
                    first_seen_at=base, last_seen_at=base)
    s.add(st); s.flush()
    pts = [(2, 1), (2, 1), (2, 1), (10, 5)]  # (mention_count, source_count) oldest first
    for i, (mc, sc) in enumerate(pts):
        s.add(IntelStoryPoint(story_id=st.id, bucket_start=base + timedelta(hours=i),
                              mention_count=mc, source_count=sc))
    s.flush()
    return st


def test_scan_story_alerts_emits_for_anomalous_story():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    st = _anomalous_story(s, d.id)

    out = alerts.scan_story_alerts(s)
    s.commit()
    assert len(out) == 1
    row = s.query(IntelAlert).one()
    assert row.scope == "story"
    assert row.story_id == st.id
    assert row.direction_id == d.id
    assert row.kind in ("spike", "source_influx")

    # Second scan within cooldown → no duplicate.
    out2 = alerts.scan_story_alerts(s)
    s.commit()
    assert out2 == []
    assert s.query(IntelAlert).count() == 1


def test_scan_story_alerts_skips_non_anomalous():
    from radar.intel import alerts
    from radar.intel.models import IntelStory
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, tzinfo=timezone.utc)
    s.add(IntelStory(direction_id=d.id, title="спокойно", is_anomaly=False,
                     first_seen_at=base, last_seen_at=base))
    s.flush()
    assert alerts.scan_story_alerts(s) == []


def _mention(s, direction_id, when, post_id):
    from radar.intel.models import IntelMention
    s.add(IntelMention(direction_id=direction_id, platform="tg", post_id=post_id,
                       author="@x", text="t", created_at=when, first_seen=when))


def test_detect_direction_burst_fires_on_latest_hour_spike():
    from radar.intel import alerts
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    n = 0
    for h in range(3):
        _mention(s, d.id, base + timedelta(hours=h, minutes=1), f"b{n}"); n += 1
    for i in range(9):
        _mention(s, d.id, base + timedelta(hours=3, minutes=i), f"s{n}"); n += 1
    s.flush()
    mag = alerts.detect_direction_burst(s, d.id)
    assert mag is not None and mag > 0


def test_detect_direction_burst_none_without_baseline():
    from radar.intel import alerts
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    _mention(s, d.id, base, "a"); _mention(s, d.id, base + timedelta(hours=1), "b")
    s.flush()
    assert alerts.detect_direction_burst(s, d.id) is None


def test_scan_direction_alerts_emits_and_dedups():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    n = 0
    for h in range(3):
        _mention(s, d.id, base + timedelta(hours=h, minutes=1), f"b{n}"); n += 1
    for i in range(9):
        _mention(s, d.id, base + timedelta(hours=3, minutes=i), f"s{n}"); n += 1
    s.flush()
    out = alerts.scan_direction_alerts(s); s.commit()
    assert len(out) == 1
    assert s.query(IntelAlert).filter_by(scope="direction", kind="direction_burst").count() == 1
    assert alerts.scan_direction_alerts(s) == []  # cooldown


def _mem_threadsafe():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from sqlalchemy.pool import StaticPool
    from radar.models import Base
    import radar.intel.models
    eng = create_engine("sqlite:///:memory:",
                        connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return _S(eng)


def _client(session):
    from fastapi import FastAPI
    from radar.intel import api as intel_api
    from radar.models import User
    app = FastAPI()
    app.include_router(intel_api.router)
    def _db_override():
        yield session
    app.dependency_overrides[intel_api.db] = _db_override
    app.dependency_overrides[intel_api.current_user] = lambda: User(id=1, email="t@t", password_hash="x")
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_alerts_list_and_ack():
    from radar.intel import alerts
    s = _mem_threadsafe()
    d = _direction(s)
    alerts._emit(s, "direction", "direction_burst", title="Курское",
                 message="Всплеск", magnitude=300.0, direction_id=d.id)
    s.commit()
    c = _client(s)

    listed = c.get("/intel/alerts?unread=true").json()
    assert len(listed) == 1
    aid = listed[0]["id"]
    assert listed[0]["direction"] == "kursk"
    assert listed[0]["acknowledged"] is False

    assert c.post(f"/intel/alerts/{aid}/ack").json()["ok"] is True
    assert c.get("/intel/alerts?unread=true").json() == []

    alerts._emit(s, "story", "spike", title="t", message="m", magnitude=1.0, story_id=9)
    s.commit()
    assert c.post("/intel/alerts/ack-all").json()["count"] == 1
    assert c.get("/intel/alerts?unread=true").json() == []


def test_run_intel_tick_emits_alerts(monkeypatch):
    """The tick runs alert scanning after clustering; an anomalous story yields a row."""
    from radar.intel import passes
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    _anomalous_story(s, d.id)
    s.commit()
    passes.run_intel_tick(s, tg_provider=None)
    assert s.query(IntelAlert).filter_by(scope="story").count() == 1
