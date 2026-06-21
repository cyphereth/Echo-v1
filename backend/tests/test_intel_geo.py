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

def test_detect_direction_by_geo_keyword():
    from radar.intel.geo import detect_direction
    assert detect_direction("удар по складу под Суджей") == "kursk"
    assert detect_direction("бои у Работино") == "zaporizhzhia"
    assert detect_direction("просто новость про погоду") is None

def test_resolve_direction_id_defaults_unassigned():
    from radar.intel import seed
    from radar.intel.tagging import resolve_direction_id
    from radar.intel.models import IntelDirection
    s = _sess()
    seed.ensure_default_directions(s)  # seeds real dirs + unassigned
    kid = resolve_direction_id(s, "kursk")
    assert s.get(IntelDirection, kid).key == "kursk"
    uid = resolve_direction_id(s, None)
    assert s.get(IntelDirection, uid).key == "unassigned"
    uid2 = resolve_direction_id(s, "nonsense")
    assert s.get(IntelDirection, uid2).key == "unassigned"
