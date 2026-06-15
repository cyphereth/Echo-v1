import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _story(s, points):
    """points: list of (mention_count, avg_sentiment, source_count), oldest first."""
    from radar.models import Story, StoryPoint
    base = datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)
    st = Story(brand_id=1, title="t", first_seen_at=base, last_seen_at=base)
    s.add(st); s.flush()
    for i, (mc, sent, src) in enumerate(points):
        s.add(StoryPoint(story_id=st.id, bucket_start=base + timedelta(hours=i),
                         mention_count=mc, avg_sentiment=sent, source_count=src))
    s.flush()
    return st


def test_fires_on_spike_and_negative():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.5, 2), (2, 0.5, 2), (2, 0.5, 2), (10, -0.5, 2)])
    assert detect_anomaly(s, st.id) is True
    assert st.is_anomaly is True


def test_fires_on_spike_and_source_influx():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.0, 1), (2, 0.0, 1), (2, 0.0, 1), (10, 0.0, 5)])
    assert detect_anomaly(s, st.id) is True


def test_no_fire_spike_only():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.0, 2), (2, 0.0, 2), (2, 0.0, 2), (10, 0.0, 2)])
    assert detect_anomaly(s, st.id) is False
    assert st.is_anomaly is False


def test_no_fire_insufficient_history():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.5, 2), (10, -0.9, 9)])  # only 2 buckets
    assert detect_anomaly(s, st.id) is False


def test_clears_when_normal():
    from radar.anomalies import detect_anomaly
    from radar.models import Story
    s = _mem()
    st = _story(s, [(2, 0.5, 2), (2, 0.5, 2), (2, 0.5, 2), (2, 0.5, 2)])
    st.is_anomaly = True; s.flush()         # pretend a prior run flagged it
    assert detect_anomaly(s, st.id) is False
    assert s.get(Story, st.id).is_anomaly is False
