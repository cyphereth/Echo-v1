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
