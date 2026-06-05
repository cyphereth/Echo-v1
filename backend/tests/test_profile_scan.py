import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from radar.api import _parse_handle


def test_parse_handle_at_username():
    assert _parse_handle("@ozon") == "ozon"

def test_parse_handle_plain():
    assert _parse_handle("ozon") == "ozon"

def test_parse_handle_tiktok_url():
    assert _parse_handle("https://www.tiktok.com/@ozon") == "ozon"

def test_parse_handle_instagram_url():
    assert _parse_handle("https://www.instagram.com/ozon.ru/") == "ozon.ru"

def test_parse_handle_empty():
    assert _parse_handle("") == ""
    assert _parse_handle("   ") == ""

def test_profile_scan_with_mock(monkeypatch):
    """profile_scan returns a profile when provider is the mock (no real TikHub)."""
    from radar import api
    from radar.providers.mock import MockProvider
    monkeypatch.setattr(api, "_get_provider", lambda: MockProvider())

    class FakeUser:
        id = 1
    body = api.ScanBody(tiktok="@testbrand", instagram="")
    result = api.profile_scan(body, user=FakeUser())
    assert result["scanned"]["tiktok"] is True
    assert result["name"]
    assert "audience_sentiment" in result


# ── RU/CIS language filter ────────────────────────────────────────────────────

def _mk_post(text, views=0):
    from radar.providers.base import Post
    from datetime import datetime, timezone
    return Post(post_id="1", platform="tiktok", author="a", followers=0,
                text=text, hashtags=[], created_at=datetime.now(timezone.utc),
                likes=0, views=views, comments=0, shares=0)

def _mk_brand(market):
    from radar.models import Brand
    b = Brand(); b.market = market; return b

def test_lang_ru_keeps_cyrillic():
    from radar.collector import _passes_language
    assert _passes_language(_mk_post("купил на озоне, отлично"), _mk_brand("ru")) is True

def test_lang_ru_drops_foreign():
    from radar.collector import _passes_language
    assert _passes_language(_mk_post("amazing delivery, loved it"), _mk_brand("ru")) is False

def test_lang_ru_keeps_viral_foreign():
    from radar.collector import _passes_language
    assert _passes_language(_mk_post("amazing delivery", views=600_000), _mk_brand("ru")) is True

def test_lang_global_keeps_everything():
    from radar.collector import _passes_language
    assert _passes_language(_mk_post("amazing delivery"), _mk_brand("global")) is True


# ── Viral threshold + hashtag spam ────────────────────────────────────────────

def test_is_viral_by_likes():
    from radar.collector import _is_viral
    assert _is_viral(_mk_post("x", views=0)) is False
    p = _mk_post("x"); p.likes = 1500
    assert _is_viral(p) is True

def test_is_viral_by_views():
    from radar.collector import _is_viral
    assert _is_viral(_mk_post("x", views=600_000)) is True

# ── Opportunity prefilter ─────────────────────────────────────────────────────

def test_opportunity_candidate_trigger():
    from radar.drafts import _is_opportunity_candidate
    assert _is_opportunity_candidate("у них скоро акция и скидки", "neutral") is True

def test_opportunity_candidate_negative():
    from radar.drafts import _is_opportunity_candidate
    assert _is_opportunity_candidate("всё дорого и плохо", "negative") is True

def test_opportunity_candidate_noise():
    from radar.drafts import _is_opportunity_candidate
    assert _is_opportunity_candidate("спасибо, классное видео", "positive") is False


def test_min_text_len_is_20():
    from radar.collector import MIN_TEXT_LEN
    assert MIN_TEXT_LEN == 20
