import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_intel_probe_direction_nullable():
    from radar.intel.models import IntelProbe
    assert IntelProbe.__table__.c.direction_id.nullable is True

def test_lexicon_model_and_unassigned_seed():
    from radar.intel.models import IntelLexicon, IntelDirection
    from radar.intel import seed
    s = _sess()
    s.add(IntelLexicon(term="300", meaning="раненые", category="casualties")); s.commit()
    assert s.query(IntelLexicon).filter_by(term="300").one().meaning == "раненые"
    d = seed.ensure_unassigned_direction(s)
    assert d.key == "unassigned"
    # idempotent
    d2 = seed.ensure_unassigned_direction(s)
    assert d2.id == d.id and s.query(IntelDirection).filter_by(key="unassigned").count() == 1
