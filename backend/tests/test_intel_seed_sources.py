# backend/tests/test_intel_seed_sources.py
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


def test_seed_file_loads_all_sources():
    from radar.intel.seed import ensure_sources_seed_loaded
    from radar.intel.models import IntelProbe

    s = _sess()
    result = ensure_sources_seed_loaded(s)
    added = result["added"]
    assert added >= 90, f"Expected >= 90 sources added, got {added}"

    count = s.query(IntelProbe).count()
    assert count == added, f"IntelProbe count {count} != added {added}"

    sides = {row[0] for row in s.query(IntelProbe.side).distinct().all()}
    assert {"ru", "ua", "by"}.issubset(sides), f"Missing sides in {sides}"

    # idempotent: second run should add 0
    result2 = ensure_sources_seed_loaded(s)
    assert result2["added"] == 0, f"Expected 0 on re-run, got {result2['added']}"


def test_extended_sides_accepted(tmp_path):
    from radar.intel.intake import ingest_sources
    from radar.intel.models import IntelProbe

    s = _sess()
    f = tmp_path / "ext.txt"
    f.write_text("@x | by | channel\n@y | mx | chat\n", encoding="utf-8")
    result = ingest_sources(s, str(f))
    assert result["added"] == 2, f"Expected 2 added, got {result['added']}"

    px = s.query(IntelProbe).filter_by(query="@x").one()
    py = s.query(IntelProbe).filter_by(query="@y").one()
    assert px.side == "by"
    assert py.side == "mx"
