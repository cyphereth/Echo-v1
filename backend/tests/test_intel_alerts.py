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
