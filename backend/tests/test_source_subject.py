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


def test_tag_geo_text_same_oblast_keeps_subject():
    """Text names a town in the SAME oblast as the source → city stays."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    bel = _dir_id(s, "belgorod")
    probe = SimpleNamespace(subject="Шебекино", direction_id=bel)
    dir_id, subject = tag_geo(s, probe, "в Грайвороне сообщают о работе ПВО")
    assert dir_id == bel
    assert subject == "Шебекино"


def test_tag_geo_text_other_oblast_drops_subject():
    """Repost about a DIFFERENT oblast → text wins, source city suppressed."""
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    bel = _dir_id(s, "belgorod")
    probe = SimpleNamespace(subject="Шебекино", direction_id=bel)
    dir_id, subject = tag_geo(s, probe, "обстрел Сумской области, горит склад")
    assert dir_id == _dir_id(s, "sumy")
    assert subject is None


def test_tag_geo_source_without_subject():
    from radar.intel.tagging import tag_geo
    s = _sess(); _seed(s)
    probe = SimpleNamespace(subject=None, direction_id=None)
    dir_id, subject = tag_geo(s, probe, "просто шум без географии")
    assert subject is None
    # falls back to unassigned bucket
    assert dir_id == _dir_id(s, "unassigned")


# ── API persists subject + direction ─────────────────────────────────────────

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
