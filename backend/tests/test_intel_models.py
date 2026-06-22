import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _mem():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.intel.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng

def test_intel_mention_has_side_and_direction():
    _mem()
    from radar.intel.models import IntelMention
    cols = set(IntelMention.__table__.columns.keys())
    assert "side" in cols and "direction_id" in cols
    for gone in ("competitor", "opportunity", "draft", "lane", "topic_id", "brand_id"):
        assert gone not in cols, f"{gone} must not be on IntelMention"

def test_intel_story_has_credibility_and_no_brandfields():
    _mem()
    from radar.intel.models import IntelStory
    cols = set(IntelStory.__table__.columns.keys())
    for need in ("source_count", "verified", "credibility", "credibility_note", "summary", "is_anomaly", "direction_id"):
        assert need in cols
    for gone in ("topic_id", "brand_id"):
        assert gone not in cols

def test_intel_schema_builds_clean():
    # no duplicate tablename / FK resolution errors on the shared Base
    _mem()
