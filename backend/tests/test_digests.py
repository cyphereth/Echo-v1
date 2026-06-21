"""test_digests.py — tests for the digest scheduler pass (domain-delegating).

Legacy tests (test_report_model_persists, test_build_daily_digest_*) used deleted
modules (radar.digests, radar.scope, radar.models.Report/Story/StoryPoint).
Those behaviors are now covered by test_digests_api.py and the brand/news domain digest
tests. Only the scheduler-level test is kept here.
"""
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


def test_run_digest_pass_calls_builder_for_autocollect_brands(monkeypatch):
    import radar.core.scheduler as SCH
    from radar.models import Brand
    s = _mem()
    s.add(Brand(id=1, name="a", auto_collect=True))
    s.add(Brand(id=2, name="b", auto_collect=False))   # excluded
    s.add(Brand(id=3, name="c", auto_collect=True))
    s.commit()

    called = []
    # scheduler now delegates to radar.brand.digests.build_brand_digest(sess, brand_id)
    monkeypatch.setattr("radar.brand.digests.build_brand_digest",
                        lambda sess, brand_id: called.append(brand_id) or None)
    SCH._run_digest_pass(s)
    assert sorted(called) == [1, 3]
