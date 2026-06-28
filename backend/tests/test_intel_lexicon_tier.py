import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa – registers IntelLexicon
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_lexicon_row_defaults_to_weak_tier():
    from radar.intel.models import IntelLexicon
    s = _sess()
    row = IntelLexicon(term="что-то", meaning="", category="x")
    s.add(row)
    s.commit()
    fetched = s.query(IntelLexicon).filter_by(term="что-то").one()
    assert fetched.tier == "weak"


def test_lexicon_tier_can_be_strong():
    from radar.intel.models import IntelLexicon
    s = _sess()
    s.add(IntelLexicon(term="калибр", meaning="", category="x", tier="strong"))
    s.commit()
    assert s.query(IntelLexicon).filter_by(term="калибр").one().tier == "strong"
