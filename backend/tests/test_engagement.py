import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radar.drafts import _system_prompt, _opportunity_prompts

# Words that signal covert astroturfing — must NOT appear in any prompt.
COVERT = ["перехват", "перехватывать", "выдавать себя", "маскир", "притвор"]


def test_system_prompt_competitor_is_transparent():
    p = _system_prompt("competitor", "Tanuki", [])
    low = p.lower()
    assert "официальн" in low                     # reply is openly from the brand
    assert not any(w in low for w in COVERT)


def test_system_prompt_niche_is_transparent():
    p = _system_prompt("niche", "Tanuki", [])
    low = p.lower()
    assert "официальн" in low
    assert not any(w in low for w in COVERT)


def test_opportunity_prompts_are_transparent():
    system, user = _opportunity_prompts(
        comment_text="где лучше заказать суши?",
        source="competitor", competitor="Якитория", brand_name="Tanuki",
    )
    blob = (system + " " + user).lower()
    assert "официальн" in blob
    assert not any(w in blob for w in COVERT)


from radar.engagement import normalize_reply, is_duplicate_reply


def test_normalize_reply_strips_case_punct_space():
    assert normalize_reply("  Привет!!  Заходи  ") == normalize_reply("привет заходи")


def test_is_duplicate_reply_detects_near_identical():
    recent = ["Заходите к нам в Tanuki, у нас акция!"]
    assert is_duplicate_reply("заходите к нам в tanuki у нас акция", recent) is True


def test_is_duplicate_reply_allows_distinct():
    recent = ["Заходите к нам в Tanuki, у нас акция!"]
    assert is_duplicate_reply("Спасибо за отзыв! Чем можем помочь?", recent) is False


def test_is_duplicate_reply_empty_history():
    assert is_duplicate_reply("любой текст", []) is False


def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_thread_already_engaged_true_after_sent():
    from datetime import datetime, timezone
    from radar.models import Mention, Comment
    from radar.engagement import thread_already_engaged
    s = _mem_session()
    m = Mention(brand_id=1, platform="tiktok", post_id="p1", author="a",
                text="t", created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    s.add(Comment(mention_id=m.id, comment_id="c1", text="x",
                  status="sent", created_at=datetime.now(timezone.utc)))
    s.commit()
    assert thread_already_engaged(s, m.id) is True


def test_thread_already_engaged_false_when_only_pending():
    from datetime import datetime, timezone
    from radar.models import Mention, Comment
    from radar.engagement import thread_already_engaged
    s = _mem_session()
    m = Mention(brand_id=1, platform="tiktok", post_id="p2", author="a",
                text="t", created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    s.add(Comment(mention_id=m.id, comment_id="c1", text="x",
                  status="pending", created_at=datetime.now(timezone.utc)))
    s.commit()
    assert thread_already_engaged(s, m.id) is False


def test_log_engagement_writes_row():
    from radar.models import EngagementLog
    from radar.engagement import log_engagement
    s = _mem_session()
    log_engagement(s, brand_id=1, mention_id=5, comment_id=9,
                   action="posted", actor="ops@x.com", text="hi")
    s.commit()
    row = s.query(EngagementLog).one()
    assert row.action == "posted" and row.actor == "ops@x.com"


def test_fetch_skips_when_thread_already_engaged(monkeypatch):
    """If a brand reply already went out under a mention, no new opportunity
    draft is generated for further comments in that same thread."""
    from datetime import datetime, timezone
    from radar import api
    from radar.models import Brand, Mention, Comment
    from radar.providers.base import Comment as ProviderComment
    s = _mem_session()
    b = Brand(id=1, name="Tanuki", sphere="суши"); s.add(b)
    m = Mention(brand_id=1, platform="tiktok", post_id="p9", author="a",
                text="t", source="competitor", competitor="Якитория",
                created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    # An already-sent reply in this thread:
    s.add(Comment(mention_id=m.id, comment_id="old", text="x",
                  status="sent", created_at=datetime.now(timezone.utc)))
    s.commit()

    # Provider returns a fresh comment that WOULD be an opportunity.
    fc = ProviderComment(comment_id="new1", author="u", followers=0,
                         text="где лучше заказать суши?", likes=5,
                         created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(api, "_get_provider",
                        lambda: type("P", (), {"fetch_comments": lambda self, *a, **k: [fc]})())
    # If evaluate_opportunity is called, fail loudly — it must be skipped.
    import radar.drafts as d
    monkeypatch.setattr(d, "evaluate_opportunity",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should skip")))
    monkeypatch.setattr("radar.spam.classify_ads_batch", lambda texts, sphere="": [False] * len(texts))
    monkeypatch.setattr("radar.spam.looks_like_ad_cheap", lambda *a, **k: False)

    api._fetch_and_store_comments(s, m)
    stored = s.query(Comment).filter_by(comment_id="new1").one()
    assert stored.is_opportunity is False and stored.draft is None


def test_comment_action_posted_logs_and_sets_status(monkeypatch):
    from datetime import datetime, timezone
    from radar import api
    from radar.models import Brand, Mention, Comment, EngagementLog
    s = _mem_session()
    s.add(Brand(id=1, name="Tanuki"))
    m = Mention(brand_id=1, platform="tiktok", post_id="p", author="a",
                text="t", created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    c = Comment(mention_id=m.id, comment_id="c", text="q", draft="ответ",
                status="pending", created_at=datetime.now(timezone.utc))
    s.add(c); s.commit()

    monkeypatch.setattr(api, "_owned_mention", lambda session, mid, user: m)
    body = api.CommentActionBody(action="posted")

    class U: id = 1; email = "ops@x.com"
    api.comment_action(c.id, body, user=U(), session=s)

    assert s.get(Comment, c.id).status == "posted"
    log = s.query(EngagementLog).filter_by(action="posted").one()
    assert log.actor == "ops@x.com" and log.comment_id == c.id
