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


def test_detect_place_returns_oblast_and_city():
    from radar.intel.geo import detect_place
    # city stem → (oblast, canonical city name); declension is matched (в Судже → Суджа)
    assert detect_place("удар по складу под Суджей") == ("kursk", "Суджа")
    assert detect_place("атака на Шостку") == ("sumy", "Шостка")
    assert detect_place("угроза БПЛА, Воронеж") == ("voronezh", "Воронеж")
    # region-level stem → oblast but no city label
    assert detect_place("обстрел Сумской области") == ("sumy", None)
    # nothing → (None, None)
    assert detect_place("просто новость про погоду") == (None, None)


def test_detect_place_ukrainian_forms_without_translation():
    """Short Ukrainian alerts that slip below the translation threshold must still match
    on the Ukrainian form stored in the gazetteer (regression for «Загроза. Суми»)."""
    from radar.intel.geo import detect_place
    assert detect_place("Загроза БпЛА. Суми") == ("sumy", "Сумы")
    assert detect_place("вибухи у Харкові") == ("kharkiv", "Харьков")
    assert detect_place("обстріл Слов'янська") == ("donetsk", "Славянск")


def test_detect_place_place_only_cities_have_no_direction():
    """Cities outside the tracked fronts give a 📍 label but direction=None — they land
    in 'unassigned' yet still show where it happened."""
    from radar.intel.geo import detect_place, detect_direction
    assert detect_place("ракетная опасность, Москва") == (None, "Москва")
    assert detect_place("вибухи у Львові") == (None, "Львов")
    assert detect_place("тревога в Казани") == (None, "Казань")
    # detect_direction (oblast-only callers) stays None for 📍-only cities
    assert detect_direction("ракетная опасность, Москва") is None

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
