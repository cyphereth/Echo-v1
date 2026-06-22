import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_retag_unassigned_uses_llm(monkeypatch):
    from radar.intel import seed, tagging
    from radar.intel.models import IntelMention, IntelDirection
    s = _sess(); seed.ensure_default_directions(s)
    uid = tagging.resolve_direction_id(s, None)  # unassigned
    s.add(IntelMention(direction_id=uid, platform="telegram", post_id="p1", author="a",
                       side="ru", text="ночью прилёт по логистике, детонация", created_at=datetime.now(timezone.utc)))
    s.commit()
    # stub the LLM to return a direction key
    monkeypatch.setattr(tagging, "_llm_classify", lambda text, keys, glossary: "kursk")
    n = tagging.retag_unassigned(s, limit=10)
    assert n == 1
    m = s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "kursk"


def test_retag_noop_without_llm(monkeypatch):
    from radar.intel import seed, tagging
    from radar.intel.models import IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    uid = tagging.resolve_direction_id(s, None)
    s.add(IntelMention(direction_id=uid, platform="telegram", post_id="p2", author="a",
                       side="ru", text="нечто без географии", created_at=datetime.now(timezone.utc)))
    s.commit()

    def _raise(*a, **k):
        from radar.core.llm import LLMNotConfigured
        raise LLMNotConfigured()

    monkeypatch.setattr("radar.core.llm.complete", _raise)
    assert tagging.retag_unassigned(s, limit=10) == 0
