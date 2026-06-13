import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _mention(s, **kw):
    from radar.models import Mention
    defaults = dict(platform="telegram", post_id="p", author="@ch", text="t",
                    created_at=datetime.now(timezone.utc), is_spam=False, source="niche")
    defaults.update(kw)
    m = Mention(**defaults); s.add(m); s.flush()
    return m


def test_fetch_new_comments_selects_only_competitor_niche_without_comments(monkeypatch):
    import radar.pipeline as P
    from radar.models import Comment
    s = _mem_session()

    m_niche = _mention(s, brand_id=1, post_id="p1", source="niche")
    m_comp  = _mention(s, brand_id=1, post_id="p2", source="competitor")
    _mention(s, brand_id=1, post_id="p3", source="brand")          # brand-lane → skip
    _mention(s, brand_id=1, post_id="p4", source="niche", is_spam=True)  # spam → skip
    m_done  = _mention(s, brand_id=1, post_id="p5", source="niche")      # already has comment → skip
    s.add(Comment(mention_id=m_done.id, comment_id="c0", text="x",
                  created_at=datetime.now(timezone.utc)))
    s.commit()

    called = []
    monkeypatch.setattr(P, "fetch_and_store_comments",
                        lambda sess, m, prov, tg: called.append(m.id) or 1)

    total = P.fetch_new_comments(s, brand_id=1, provider=object(), tg_provider=object())

    assert set(called) == {m_niche.id, m_comp.id}
    assert total == 2


def test_fetch_new_comments_scoped_to_brand(monkeypatch):
    import radar.pipeline as P
    s = _mem_session()
    m1 = _mention(s, brand_id=1, post_id="a", source="niche")
    _mention(s, brand_id=2, post_id="b", source="niche")  # other brand → excluded
    s.commit()

    called = []
    monkeypatch.setattr(P, "fetch_and_store_comments",
                        lambda sess, m, prov, tg: called.append(m.id) or 0)
    P.fetch_new_comments(s, brand_id=1, provider=None, tg_provider=None)
    assert called == [m1.id]


def test_looks_like_intent_fires_on_imperative_ask_without_question_mark():
    from radar.pipeline import _looks_like_intent
    assert _looks_like_intent("посоветуйте хороший ресторан в центре")   # no "?"
    assert _looks_like_intent("помогите выбрать смартфон до 30к")
    assert not _looks_like_intent("сегодня отличная погода")
    assert _looks_like_intent("стоит ли брать этот ноутбук?")           # soft cue + "?"


def test_fetch_new_comments_skips_chat_messages(monkeypatch):
    import radar.pipeline as P
    from radar.models import Mention
    s = _mem_session()

    def mk(pid):
        m = Mention(brand_id=1, platform="telegram", post_id=pid, author="@u", text="t",
                    source="niche", is_spam=False,
                    created_at=datetime.now(timezone.utc))
        s.add(m); s.flush(); return m

    chat   = mk("foodmsk/1")   # chat message — no reply thread, must be skipped
    normal = mk("abc123")      # channel/post mention — eligible
    s.commit()

    called = []
    monkeypatch.setattr(P, "fetch_and_store_comments",
                        lambda sess, m, prov, tg: called.append(m.post_id) or 0)
    P.fetch_new_comments(s, brand_id=1, provider=None, tg_provider=None)
    assert called == ["abc123"]
