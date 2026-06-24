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
