import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
import pytest


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


@pytest.mark.parametrize("text, expected", [
    ("сирена погар",                       "bryansk"),    # the user's example
    ("опасность БПЛА в Выгоничах",          "bryansk"),
    ("обстрел Шебекино подтверждён",        "belgorod"),
    ("работа ПВО над Грайвороном",          "belgorod"),
    ("бои под Суджей продолжаются",         "kursk"),
    ("прилёт в Россоши",                    "voronezh"),
    ("тревога в Мценске",                   "oryol"),
    ("над Таганрогом сбили дрон",           "rostov"),
    ("взрывы в Севастополе",                "crimea"),
    ("атака на Шостку",                     "sumy"),
    ("удар по Чернигову",                   "chernihiv"),
    ("бои за Купянск",                      "kharkiv"),
    ("активность под Кременной",            "luhansk"),
    ("штурм Покровска",                     "donetsk"),
    ("обстрел Орехова",                     "zaporizhzhia"),
    ("ВСУ под Берислав",                    "kherson"),
    ("прилёт по Никополю",                  "dnipro"),
    ("ППО работает над Киевом",             "kyiv"),
])
def test_gazetteer_directions(text, expected):
    from radar.intel.geo import detect_direction
    assert detect_direction(text) == expected, f"{text!r} -> {detect_direction(text)!r}, want {expected!r}"


def test_no_match_returns_none():
    from radar.intel.geo import detect_direction
    assert detect_direction("обычный пост без географии вообще") is None


def test_retag_unassigned_geo_assigns_known_settlement():
    from radar.intel import seed, tagging
    from radar.intel.models import IntelMention, IntelDirection
    s = _sess()
    seed.ensure_default_directions(s)
    uid = seed.ensure_unassigned_direction(s).id
    # a post stuck as 'unassigned' that mentions Погар (Брянская обл.)
    s.add(IntelMention(direction_id=uid, platform="telegram", post_id="p1", author="@x",
                       side="ru", text="сирена погар, опасность БПЛА",
                       created_at=datetime.now(timezone.utc)))
    s.commit()

    n = tagging.retag_unassigned_geo(s)
    assert n == 1
    m = s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "bryansk"
