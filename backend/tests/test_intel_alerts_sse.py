import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from datetime import datetime, timezone


def _mem_engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from radar.models import Base
    import radar.intel.models
    eng = create_engine("sqlite:///:memory:",
                        connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


def test_event_gen_emits_named_alert_frame(monkeypatch):
    """After after_alert_id, a new IntelAlert is delivered as an `event: alert` frame."""
    from sqlalchemy.orm import Session
    from radar.intel import api as intel_api
    from radar.intel import alerts
    from radar.intel.models import IntelDirection

    eng = _mem_engine()
    monkeypatch.setattr(intel_api, "get_session", lambda: Session(eng))
    monkeypatch.setattr(intel_api, "_auth_user_from_header", lambda authorization: object())

    async def _stop(_):
        raise asyncio.CancelledError()
    monkeypatch.setattr(intel_api.asyncio, "sleep", _stop)

    s = Session(eng)
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    a = alerts._emit(s, "direction", "direction_burst", title="Курское",
                     message="Всплеск", magnitude=300.0, direction_id=d.id)
    s.commit()
    start_before = a.id - 1  # stream from before this alert
    s.close()

    async def drain():
        resp = await intel_api.intel_stream_live(after_id=0, after_alert_id=start_before,
                                                 direction=None, authorization="Bearer x")
        chunks = []
        try:
            async for c in resp.body_iterator:
                chunks.append(c)
        except asyncio.CancelledError:
            pass
        return "".join(chunks)

    out = asyncio.new_event_loop().run_until_complete(drain())
    assert "event: alert" in out
    assert "Всплеск" in out
