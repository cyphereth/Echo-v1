"""Tests for the curator spam filter: stop-words (fast layer) + LLM example layer,
and their integration into collector.collect_probe."""
import os
import sys
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


# ── blocked_by_word ──────────────────────────────────────────────────────────

def test_blocked_by_word_boundary_and_case():
    from radar.intel.spam_filter import blocked_by_word

    bl = ["реклама", "купить курс"]
    assert blocked_by_word("Свежая РЕКЛАМА тут", bl) is True          # case-insensitive
    assert blocked_by_word("успей купить курс дёшево", bl) is True    # multi-word phrase
    assert blocked_by_word("обстрел района, есть прилёты", bl) is False
    # word-boundary: substring inside a longer word must NOT match
    assert blocked_by_word("рекламациянеподходит", ["реклама"]) is False


def test_blocked_by_word_empty_blocklist():
    from radar.intel.spam_filter import blocked_by_word
    assert blocked_by_word("любой текст", []) is False


# ── classify_spam_batch fail-open ────────────────────────────────────────────

def test_classify_spam_batch_fail_open_no_key(monkeypatch):
    from radar.intel import spam_filter
    monkeypatch.setattr(spam_filter, "LLM_API_KEY", "")
    out = spam_filter.classify_spam_batch(["a", "b"], ["пример мусора"])
    assert out == [False, False]


def test_classify_spam_batch_no_examples():
    from radar.intel import spam_filter
    # No examples → nothing to compare against → drop nothing, regardless of key.
    assert spam_filter.classify_spam_batch(["a", "b"], []) == [False, False]


def test_classify_spam_batch_empty():
    from radar.intel import spam_filter
    assert spam_filter.classify_spam_batch([], ["x"]) == []


# ── collector integration: stop-word drops a post ────────────────────────────

def test_collect_drops_stop_word_post():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelLexicon, IntelSpam

    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="удар", meaning="strike", category="military", tier="strong"))
    s.add(IntelSpam(kind="word", value="реклама"))
    s.commit()

    p = IntelProbe(platform="telegram", kind="channel", query="https://t.me/rbc", side="ru")
    s.add(p)
    s.commit()

    spam_post = SimpleNamespace(post_id="@rbc/1", author="@rbc",
        text="удар по складу — а также реклама нашего канала, подпишись",
        created_at=datetime.now(timezone.utc), likes=0)
    good_post = SimpleNamespace(post_id="@rbc/2", author="@rbc",
        text="удар по складу под Суджей, новые подробности с места",
        created_at=datetime.now(timezone.utc), likes=0)

    def mock_search(q, kind, cursor):
        return SimpleNamespace(posts=[spam_post, good_post], cursor=None)

    prov = SimpleNamespace(search=mock_search)
    n = collector.collect_probe(s, p, prov)

    assert n == 1, f"expected only the non-spam post stored, got {n}"
    texts = [m.text for m in s.query(IntelMention).all()]
    assert all("реклама" not in t for t in texts)


# ── collector integration: LLM layer flags a buffered post ───────────────────

def test_collect_drops_llm_flagged_post(monkeypatch):
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelLexicon, IntelSpam

    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="удар", meaning="strike", category="military", tier="strong"))
    s.add(IntelSpam(kind="example", value="подпишись на наш канал, лучшие новости"))
    s.commit()

    p = IntelProbe(platform="telegram", kind="channel", query="https://t.me/rbc", side="ru")
    s.add(p)
    s.commit()

    posts = [
        SimpleNamespace(post_id="@rbc/1", author="@rbc",
            text="удар по складу, подписывайтесь на канал за новостями",
            created_at=datetime.now(timezone.utc), likes=0),
        SimpleNamespace(post_id="@rbc/2", author="@rbc",
            text="удар по складу под Суджей, новые подробности с места",
            created_at=datetime.now(timezone.utc), likes=0),
    ]

    # Mock the LLM layer: flag the first buffered post as spam, keep the second.
    monkeypatch.setattr(collector, "classify_spam_batch",
                        lambda texts, examples: [True, False])

    def mock_search(q, kind, cursor):
        return SimpleNamespace(posts=posts, cursor=None)

    n = collector.collect_probe(s, p, SimpleNamespace(search=mock_search))

    assert n == 1, f"LLM-flagged post should be dropped, got {n}"
    assert s.query(IntelMention).count() == 1
