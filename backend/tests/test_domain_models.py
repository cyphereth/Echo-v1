import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mem():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.news.models  # noqa: F401  (register tables)
    import radar.brand.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_news_mention_is_lean():
    _mem()
    from radar.news.models import NewsMention
    cols = set(NewsMention.__table__.columns.keys())
    assert "topic_id" in cols
    # brand-only fields must NOT leak into news
    for gone in ("competitor", "opportunity", "draft", "lane", "tone", "phase", "is_hot", "status"):
        assert gone not in cols, f"{gone} should not be on NewsMention"


def test_news_story_has_credibility():
    _mem()
    from radar.news.models import NewsStory
    cols = set(NewsStory.__table__.columns.keys())
    for need in ("source_count", "verified", "credibility", "credibility_note", "summary"):
        assert need in cols


def test_brand_story_has_no_credibility():
    _mem()
    from radar.brand.models import BrandStory
    cols = set(BrandStory.__table__.columns.keys())
    assert "credibility" not in cols
    assert "verified" not in cols
