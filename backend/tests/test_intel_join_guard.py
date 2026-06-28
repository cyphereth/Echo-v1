# backend/tests/test_intel_join_guard.py
"""Joins must happen at most once per source — re-issuing JoinChannelRequest on every
collect tick is what earns the account multi-hour Telegram flood bans."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


@pytest.fixture(autouse=True)
def _isolate_join_state(tmp_path, monkeypatch):
    """Point the shared join-state at a throwaway file and clear its cache, so each
    test starts with nothing joined and never touches the real subscribed.json."""
    from radar.intel import subscribe
    monkeypatch.setattr(subscribe, "_STATE_FILE", str(tmp_path / "subscribed.json"))
    monkeypatch.setattr(subscribe, "_done_cache", None)
    monkeypatch.setattr(subscribe, "_JOIN_INTERVAL", 0.0)  # no real sleeping in tests
    yield


def _channel_provider(join_calls):
    posts = [SimpleNamespace(post_id="@rybar/1", author="@rybar", text="бои под Авдеевкой сегодня",
                             followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]

    def join_channel(h):
        join_calls.append(h)
        return True
    return SimpleNamespace(search=lambda q, k, c: SimpleNamespace(posts=posts, cursor=None),
                           join_channel=join_channel)


def _due_channel_probe(s):
    from radar.intel import seed
    from radar.intel.models import IntelProbe, IntelLexicon
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="бои", meaning="combat", category="military"))
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    p = IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru", next_run_at=past)
    s.add(p); s.commit()
    return p


def test_channel_joined_once_across_two_ticks():
    from radar.intel import passes
    s = _sess()
    probe = _due_channel_probe(s)
    calls = []
    prov = _channel_provider(calls)

    passes.run_intel_collect(s, prov)
    # make it due again, run a second tick
    probe.next_run_at = datetime.now(timezone.utc) - timedelta(hours=1)
    s.commit()
    passes.run_intel_collect(s, prov)

    assert calls == ["@rybar"], f"join_channel should fire exactly once, got {calls}"


def test_ensure_joined_propagates_floodwait():
    from radar.intel import passes
    from radar.core.providers.telegram import TelegramFloodWait
    s = _sess()
    _due_channel_probe(s)

    def join_channel(h):
        raise TelegramFloodWait(29000)
    prov = SimpleNamespace(search=lambda q, k, c: SimpleNamespace(posts=[], cursor=None),
                           join_channel=join_channel)

    # run_intel_collect must catch the propagated flood and abort cleanly (no raise).
    passes.run_intel_collect(s, prov)
    # collect never ran for the probe → no mentions stored
    from radar.intel.models import IntelMention
    assert s.query(IntelMention).count() == 0


def test_provider_join_channel_propagates_parked_floodwait():
    """When _await fast-fails inside a parked flood window it raises the domain
    TelegramFloodWait; join_channel must propagate it, not swallow it as a plain
    failure and return False."""
    from radar.core.providers.telegram import TelegramProvider, TelegramFloodWait

    class FakeClient:
        def get_entity(self, h):
            raise TelegramFloodWait(29000)
    p = TelegramProvider(client=FakeClient())
    with pytest.raises(TelegramFloodWait):
        p.join_channel("@rybar")


def test_subscribe_run_respects_per_run_cap(monkeypatch):
    from radar.intel import subscribe
    monkeypatch.setattr(subscribe, "_JOIN_MAX_PER_RUN", 2)
    calls = []

    monkeypatch.setattr(subscribe, "build_source_map",
                        lambda s: ({}, ["@a", "@b", "@c", "@d"], []))
    monkeypatch.setattr(subscribe, "get_session", lambda: SimpleNamespace(close=lambda: None))

    prov = SimpleNamespace(join_channel=lambda h: calls.append(h) or True)
    counts = subscribe.run(prov)

    assert len(calls) == 2, f"cap=2 should join only 2, joined {calls}"
    assert counts.get("cap_reached") is True
    assert counts["channels_ok"] == 2


def test_subscribe_run_skips_already_joined(monkeypatch):
    from radar.intel import subscribe
    subscribe.mark_joined("@a")  # pretend we already joined @a
    calls = []
    monkeypatch.setattr(subscribe, "build_source_map",
                        lambda s: ({}, ["@a", "@b"], []))
    monkeypatch.setattr(subscribe, "get_session", lambda: SimpleNamespace(close=lambda: None))
    prov = SimpleNamespace(join_channel=lambda h: calls.append(h) or True)

    counts = subscribe.run(prov)
    assert calls == ["@b"], f"@a already joined, should only join @b, got {calls}"
    assert counts["skipped"] == 1
