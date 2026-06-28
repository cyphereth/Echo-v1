"""Tests for source-level locality (subject): tag_geo precedence rules and the
sources API persisting subject + direction. See docs design 2026-06-28."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from types import SimpleNamespace


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _seed(s):
    from radar.intel import seed
    seed.ensure_default_directions(s)
    s.commit()


def _dir_id(s, key):
    from radar.intel.models import IntelDirection
    return s.query(IntelDirection).filter_by(key=key).one().id


# ── tag_geo precedence ───────────────────────────────────────────────────────

def test_tag_geo_empty_text_falls_back_to_source():
    """Local chat post with no place named → gets the source's oblast + city."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    bel = _dir_id(s, "belgorod")
    probe = SimpleNamespace(subject="Шебекино", direction_id=bel)
    dir_id, subject = tag_geo(s, probe, "прилёт по окраине, без света полрайона")
    assert dir_id == bel
    assert subject == "Шебекино"


def test_tag_geo_text_city_wins_over_source_subject():
    """Text names a town in the SAME oblast as the source → the TEXT's city wins
    (it describes the concrete event); the source subject is only a fallback."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    bel = _dir_id(s, "belgorod")
    probe = SimpleNamespace(subject="Шебекино", direction_id=bel)
    dir_id, subject = tag_geo(s, probe, "в Грайвороне сообщают о работе ПВО")
    assert dir_id == bel
    assert subject == "Грайворон"


def test_tag_geo_region_only_text_keeps_source_subject():
    """Text names only the oblast (region-level stem, no city) → source subject kept."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    bel = _dir_id(s, "belgorod")
    probe = SimpleNamespace(subject="Шебекино", direction_id=bel)
    # "белгород" stem in text resolves a city; use an oblast-only phrasing instead:
    dir_id, subject = tag_geo(s, probe, "сводка по Сумской области без деталей")
    # text points to another oblast (sumy) with no city → no false source city
    assert dir_id == _dir_id(s, "sumy")
    assert subject is None


def test_tag_geo_bot_aggregator_gets_city_from_text():
    """A bot-aggregator source (no subject) still gets 📍 from the post text."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    probe = SimpleNamespace(subject=None, direction_id=None)
    dir_id, subject = tag_geo(s, probe, "Воронеж. Угроза применения БПЛА. Перейдите в укрытие!")
    assert dir_id == _dir_id(s, "voronezh")
    assert subject == "Воронеж"


def test_tag_geo_text_other_oblast_drops_subject():
    """Repost about a DIFFERENT oblast → text wins, source city suppressed."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    bel = _dir_id(s, "belgorod")
    probe = SimpleNamespace(subject="Шебекино", direction_id=bel)
    dir_id, subject = tag_geo(s, probe, "обстрел Сумской области, горит склад")
    assert dir_id == _dir_id(s, "sumy")
    assert subject is None


def test_tag_geo_place_only_city_gets_locality_no_front():
    """A bot-aggregator post about a city outside the tracked fronts (Москва) → 📍 set,
    direction falls back to 'unassigned' (no front spawned for it)."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    probe = SimpleNamespace(subject=None, direction_id=None)
    dir_id, subject = tag_geo(s, probe, "Москва. Объявлена опасность атаки БПЛА")
    assert subject == "Москва"
    assert dir_id == _dir_id(s, "unassigned")


def test_tag_geo_source_without_subject():
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    probe = SimpleNamespace(subject=None, direction_id=None)
    dir_id, subject = tag_geo(s, probe, "просто шум без географии")
    assert subject is None
    # falls back to unassigned bucket
    assert dir_id == _dir_id(s, "unassigned")


# ── API persists subject + direction ─────────────────────────────────────────

def test_hide_mention_hides_cross_channel_reposts():
    """Скрытие поста прячет ВСЕХ близнецов с той же сигнатурой контента — иначе после
    рефреша всплывёт дубликат и пост будто вернётся (регрессия)."""
    from datetime import datetime, timezone
    from radar.intel import api
    from radar.intel.models import IntelMention, IntelDirection
    s = _sess(); _seed(s)
    d = s.query(IntelDirection).first()
    now = datetime.now(timezone.utc)
    text = "Прилёт по окраине, горит склад"
    # Один и тот же текст в трёх каналах (verbatim repost) + footer/ссылка — сигнатура та же.
    a = IntelMention(direction_id=d.id, platform="telegram", post_id="ch1/1",
                     author="@a", text=text, created_at=now)
    b = IntelMention(direction_id=d.id, platform="telegram", post_id="ch2/2",
                     author="@b", text=text + " https://t.me/x", created_at=now)
    c = IntelMention(direction_id=d.id, platform="telegram", post_id="ch3/3",
                     author="@c", text="совсем другой пост", created_at=now)
    s.add_all([a, b, c]); s.commit()

    res = api.intel_mention_hide(a.id, user=None, session=s)
    assert res["hidden_count"] == 2  # a и его близнец b
    s.refresh(a); s.refresh(b); s.refresh(c)
    assert a.hidden is True
    assert b.hidden is True
    assert c.hidden is False  # другой контент не трогаем


def test_sources_create_and_patch_persist_subject_direction():
    from radar.intel import api
    s = _sess(); _seed(s)

    created = api.intel_sources_create(
        {"link": "https://t.me/shebekino_chat", "side": "ru", "kind": "chat",
         "subject": "Шебекино", "direction": "belgorod"},
        user=None, session=s)
    assert created["created"] is True
    assert created["subject"] == "Шебекино"
    assert created["direction"] == "belgorod"

    updated = api.intel_sources_update(
        created["id"], {"subject": "Грайворон", "direction": "belgorod"},
        user=None, session=s)
    assert updated["subject"] == "Грайворон"
    assert updated["direction"] == "belgorod"

    listed = api.intel_sources_list(user=None, session=s)
    row = next(r for r in listed if r["id"] == created["id"])
    assert row["subject"] == "Грайворон"
    assert row["direction"] == "belgorod"
