import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


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
