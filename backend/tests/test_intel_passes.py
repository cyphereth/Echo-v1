# backend/tests/test_intel_passes.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_run_intel_collect_noop_without_provider():
    from radar.intel.passes import run_intel_collect
    run_intel_collect(_sess(), None)  # must not raise

def test_run_intel_collect_collects_due_channel():
    from radar.intel import seed, passes
    from radar.intel.models import IntelProbe, IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s.add(IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru", next_run_at=past)); s.commit()
    posts=[SimpleNamespace(post_id="@rybar/1", author="@rybar", text="бои под Авдеевкой нарастают сегодня",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    passes.run_intel_collect(s, prov)
    assert s.query(IntelMention).count() == 1


def test_intel_tick_collects_and_clusters(monkeypatch):
    from radar.intel import seed, passes, stories
    from radar.intel.models import IntelProbe, IntelMention, IntelStory, IntelDirection
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    s = _sess(); seed.ensure_default_directions(s)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s.add(IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru", next_run_at=past)); s.commit()
    posts=[SimpleNamespace(post_id=f"@rybar/{i}", author=f"@a{i}", text="удар по Работино, активизация",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0) for i in range(3)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    # the tick: collect, then cluster each direction that got mentions
    passes.run_intel_tick(s, tg_provider=prov, embed=lambda t:[float(len(t))])
    assert s.query(IntelMention).count() == 3
    assert s.query(IntelStory).filter(IntelStory.direction_id.isnot(None)).count() >= 1


def test_intel_tick_stories_persist_across_session_boundary(tmp_path):
    """Cross-session persistence test: stories must be committed, not just flushed.

    Uses a temp-file SQLite DB (not :memory:) so a second session truly sees
    only committed data. Before the fix, IntelStory count was 0 in session B.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa: F401 — registers IntelDirection etc.
    from radar.intel import seed, passes
    from radar.intel.models import IntelProbe, IntelStory, IntelDirection
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace

    db_path = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    posts = [
        SimpleNamespace(
            post_id=f"@r/{i}",
            author=f"@a{i}",
            text="удар по складу под Суджей детонация",
            followers=0,
            created_at=datetime.now(timezone.utc),
            hashtags=[],
            likes=5,
        )
        for i in range(3)
    ]
    prov = SimpleNamespace(search=lambda q, k, c: SimpleNamespace(posts=posts, cursor=None))

    # Session A: seed, run tick, then CLOSE
    with Session(engine) as s:
        seed.ensure_default_directions(s)
        s.add(IntelProbe(
            platform="telegram", kind="channel", query="@r", side="ru",
            next_run_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        s.commit()
        passes.run_intel_tick(s, tg_provider=prov, embed=lambda t: [float(len(t))])
    # session A is now closed — any uncommitted data would be lost

    # Session B: open a brand-new session on the same DB file
    with Session(engine) as s2:
        story_count = s2.query(IntelStory).filter(IntelStory.direction_id.isnot(None)).count()

    assert story_count >= 1, (
        f"Expected at least 1 persisted IntelStory across session boundary, got {story_count}. "
        "run_intel_tick must commit after update_stories."
    )
