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
