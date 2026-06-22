# backend/tests/test_intel_passes.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_run_intel_collect_noop_without_provider():
    from radar.intel.passes import run_intel_collect
    run_intel_collect(_sess(), None)  # must not raise

def test_run_intel_collect_collects_due_channel():
    from radar.intel import seed, passes
    from radar.intel.models import IntelProbe, IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s.add(IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru", next_run_at=past)); s.commit()
    posts=[SimpleNamespace(post_id="@rybar/1", author="@rybar", text="бои под Авдеевкой нарастают сегодня",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    passes.run_intel_collect(s, prov)
    assert s.query(IntelMention).count() == 1
