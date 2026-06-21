# backend/tests/test_intel_intake.py
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

def test_ingest_sources_upserts(tmp_path):
    from radar.intel.intake import ingest_sources
    from radar.intel.models import IntelProbe
    s = _sess()
    f = tmp_path / "src.txt"
    f.write_text("# my sources\n@rybar | ru | channel\nhttps://t.me/foo | ua | chat\n\n", encoding="utf-8")
    out = ingest_sources(s, str(f))
    assert out == {"added": 2, "updated": 0}
    p = s.query(IntelProbe).filter_by(query="@rybar").one()
    assert p.side == "ru" and p.kind == "channel"
    # re-ingest with changed side -> update, not duplicate
    f.write_text("@rybar | ua | channel\n", encoding="utf-8")
    out2 = ingest_sources(s, str(f))
    assert out2 == {"added": 0, "updated": 1}
    assert s.query(IntelProbe).filter_by(query="@rybar").one().side == "ua"
    assert s.query(IntelProbe).count() == 2
