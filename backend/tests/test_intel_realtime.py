import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from types import SimpleNamespace


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _post(post_id, text, author="@src"):
    return SimpleNamespace(
        post_id=post_id, platform="telegram", author=author, followers=0,
        text=text, hashtags=[], created_at=datetime.now(timezone.utc),
        likes=0, views=0, comments=0, shares=0, sound_id=None,
    )


def test_build_source_map_splits_public_and_invite():
    from radar.intel.realtime import build_source_map
    from radar.intel.models import IntelProbe
    s = _sess()
    s.add_all([
        IntelProbe(platform="telegram", kind="channel", query="https://t.me/nexta_live", side="by"),
        IntelProbe(platform="telegram", kind="chat", query="@some_chat", side="ru"),
        IntelProbe(platform="telegram", kind="chat", query="https://t.me/+AbCdEf123", side="ua"),
    ])
    s.commit()
    by_user, join_handles, invite_links = build_source_map(s)
    assert by_user["nexta_live"]["side"] == "by"
    assert by_user["nexta_live"]["kind"] == "channel"
    assert by_user["nexta_live"]["handle"] == "@nexta_live"
    assert by_user["some_chat"]["side"] == "ru"
    assert "@nexta_live" in join_handles and "@some_chat" in join_handles
    assert len(invite_links) == 1 and invite_links[0][1] == "ua"
    # invite link is NOT in the username lookup (no resolvable @handle)
    assert all("+" not in k for k in by_user)


def test_build_source_map_carries_subject_and_direction():
    """Карта источников несёт subject + direction_id источника — иначе live-лента не
    знает, какой нас. пункт проставить свежему посту (регрессия)."""
    from radar.intel import seed
    from radar.intel.realtime import build_source_map
    from radar.intel.models import IntelProbe, IntelDirection
    s = _sess()
    seed.ensure_default_directions(s)
    bel = s.query(IntelDirection).filter_by(key="belgorod").one().id
    s.add(IntelProbe(platform="telegram", kind="chat", query="@shebekino_chat",
                     side="ru", subject="Шебекино", direction_id=bel))
    s.commit()
    by_user, _, _ = build_source_map(s)
    assert by_user["shebekino_chat"]["subject"] == "Шебекино"
    assert by_user["shebekino_chat"]["direction_id"] == bel


def test_store_realtime_attaches_source_subject():
    """Live-пост без явной географии в тексте получает нас. пункт источника — как поллер
    (collector). Раньше realtime игнорировал subject и место не показывалось в ленте."""
    from radar.intel import seed
    from radar.intel.realtime import store_realtime_post
    from radar.intel.models import IntelMention, IntelDirection
    s = _sess()
    seed.ensure_default_directions(s)
    bel = s.query(IntelDirection).filter_by(key="belgorod").one().id
    text = "прилёт по окраине, горит склад, без света полрайона сегодня вечером"
    assert store_realtime_post(s, _post("c/77", text), "ru", "chat", ["прилёт"],
                               subject="Шебекино", src_direction_id=bel) is True
    s.commit()
    m = s.query(IntelMention).filter_by(post_id="c/77").one()
    assert m.subject == "Шебекино"
    assert m.direction_id == bel


def test_store_realtime_curator_keyword_admits_non_lexicon_post():
    """A realtime channel post that misses the lexicon is admitted when it matches a
    curator-managed positive keyword passed in."""
    from radar.intel import seed
    from radar.intel.realtime import store_realtime_post
    from radar.intel.models import IntelMention, IntelLexicon
    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="обстрел", meaning="shelling", category="military"))
    s.commit()
    lex = ["обстрел"]

    text = "сильное наводнение затопило центральные улицы города сегодня утром"
    # No keyword → lexicon miss → dropped
    assert store_realtime_post(s, _post("c/10", text), "ru", "channel", lex) is False
    # Curator keyword present → admitted
    assert store_realtime_post(s, _post("c/11", text), "ru", "channel", lex,
                               keywords=["наводнение"]) is True
    s.commit()
    assert s.query(IntelMention).count() == 1


def test_store_channel_post_relevance_and_dedup():
    from radar.intel import seed
    from radar.intel.realtime import store_realtime_post
    from radar.intel.models import IntelMention, IntelLexicon
    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="обстрел", meaning="shelling", category="military"))
    s.commit()
    lex = ["обстрел"]

    # irrelevant channel post → not stored
    assert store_realtime_post(s, _post("c/1", "сегодня хорошая погода и солнце светит ярко"), "ru", "channel", lex) is False
    # relevant channel post → stored
    assert store_realtime_post(s, _post("c/2", "сообщают про обстрел района сегодня вечером сильный"), "ru", "channel", lex) is True
    s.commit()
    assert s.query(IntelMention).count() == 1
    # same post_id again (realtime + poll overlap) → deduped, no second row
    assert store_realtime_post(s, _post("c/2", "сообщают про обстрел района сегодня вечером сильный"), "ru", "channel", lex) is False
    s.commit()
    assert s.query(IntelMention).count() == 1


def test_store_realtime_translates_ukrainian_before_gates(monkeypatch):
    # Realtime is the fast path for fresh posts; it must translate uk→ru like the
    # poller, otherwise Ukrainian posts land untranslated AND the russian lexicon
    # gate misses them. Mock the translator so the test needs no network.
    import radar.intel.realtime as rt
    from radar.intel import seed
    from radar.intel.models import IntelMention, IntelLexicon
    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="обстрел", meaning="shelling", category="military"))
    s.commit()
    lex = ["обстрел"]

    ua = "ворог здійснив обстріл району увечері, є поранені серед мирних мешканців"
    monkeypatch.setattr(rt, "maybe_translate",
                        lambda t: "враг совершил обстрел района вечером, есть раненые среди мирных жителей")
    assert rt.store_realtime_post(s, _post("c/9", ua), "ru", "channel", lex) is True
    s.commit()
    row = s.query(IntelMention).filter_by(post_id="c/9").one()
    assert "обстрел" in row.text and "обстріл" not in row.text


def test_store_short_channel_post_dropped():
    from radar.intel import seed
    from radar.intel.realtime import store_realtime_post
    from radar.intel.models import IntelMention, IntelLexicon
    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="обстрел", meaning="shelling", category="military"))
    s.commit()
    # contains the keyword but too short after stripping → dropped by length gate
    assert store_realtime_post(s, _post("c/3", "обстрел"), "ru", "channel", ["обстрел"]) is False
    s.commit()
    assert s.query(IntelMention).count() == 0


def test_store_realtime_reply_resolves_thread_locally():
    """A realtime reply whose parent is already in the DB gets its thread chain
    built immediately (no network), so the «в ответ на» context is ready at once."""
    from radar.intel import seed
    from radar.intel.realtime import store_realtime_post
    from radar.intel.models import IntelMention, IntelThreadContext, IntelLexicon
    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="обстрел", meaning="shelling", category="military"))
    s.commit()
    lex = ["обстрел"]

    # Parent already collected from the same chat.
    assert store_realtime_post(
        s, _post("grp/199", "сообщают про обстрел района вечером сильный"), "ru", "chat", lex
    ) is True
    s.commit()

    # New reply to grp/199.
    reply = _post("grp/200", "подтверждаю обстрел был очень сильный сегодня", author="@b")
    reply.reply_to_tg_id = "199"
    assert store_realtime_post(s, reply, "ru", "chat", lex) is True
    s.commit()

    r = s.query(IntelMention).filter_by(post_id="grp/200").one()
    assert r.context_fetched is True
    parent = s.query(IntelMention).filter_by(post_id="grp/199").one()
    assert r.reply_to_id == parent.id
    chain = s.query(IntelThreadContext).filter_by(mention_id=r.id, role="parent").all()
    assert [c.tg_msg_id for c in chain] == ["199"]
