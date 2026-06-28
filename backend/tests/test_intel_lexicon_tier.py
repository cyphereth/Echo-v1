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


def _write_seed(tmp_path):
    import json
    data = {
        "_meta": {
            "overrides_weak": ["работа"],
            "overrides_strong": ["сирена"],
        },
        "missiles_weapons": {"description": "оружие", "tier": "strong",
                             "words": ["калибр", "работа"]},
        "alerts_status":    {"description": "тревоги", "tier": "weak",
                             "words": ["опасность", "сирена"]},
    }
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_ingest_assigns_tier_from_category(tmp_path):
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    ingest_lexicon_json(s, _write_seed(tmp_path))
    # strong-категория → strong
    assert s.query(IntelLexicon).filter_by(term="калибр").one().tier == "strong"
    # weak-категория → weak
    assert s.query(IntelLexicon).filter_by(term="опасность").one().tier == "weak"


def test_ingest_applies_overrides(tmp_path):
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    ingest_lexicon_json(s, _write_seed(tmp_path))
    # overrides_weak бьёт strong-категорию
    assert s.query(IntelLexicon).filter_by(term="работа").one().tier == "weak"
    # overrides_strong бьёт weak-категорию
    assert s.query(IntelLexicon).filter_by(term="сирена").one().tier == "strong"


def test_ingest_updates_tier_on_reingest(tmp_path):
    """Повторный ингест меняет tier у существующей строки, не плодит дубли."""
    import json
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    seed = _write_seed(tmp_path)
    ingest_lexicon_json(s, seed)
    # переписать seed: калибр теперь в weak-категории без override
    data = {"_meta": {}, "misc": {"description": "x", "tier": "weak", "words": ["калибр"]}}
    import pathlib
    pathlib.Path(seed).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ingest_lexicon_json(s, seed)
    rows = s.query(IntelLexicon).filter_by(term="калибр").all()
    assert len(rows) == 1
    assert rows[0].tier == "weak"
