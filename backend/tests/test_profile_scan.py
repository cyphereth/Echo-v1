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


# ── Ad / spam cheap rules ─────────────────────────────────────────────────────

def test_spam_sales_phrase():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("Лучшие товары! Артикул в профиле, заказывайте", "user1", []) is True

def test_spam_seller_username():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("классная штука для дома и кухни каждый день", "wb_goldy", []) is True

def test_spam_too_short():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("огонь", "user1", []) is True

def test_spam_too_long():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("ж" * 200, "user1", []) is True

def test_spam_hashtag_stuffing():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("норм пост про доставку озон сегодня", "user1",
                               ["a", "b", "c", "d", "e"]) is True

def test_spam_real_post_passes():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("заказал на озоне, доставили за два дня, всё отлично", "katya_msk", ["озон"]) is False

def test_classify_ads_batch_no_key():
    from radar.spam import classify_ads_batch
    import radar.spam as sp
    old = sp.LLM_API_KEY; sp.LLM_API_KEY = ""
    try:
        assert classify_ads_batch(["a", "b", "c"]) == [False, False, False]
    finally:
        sp.LLM_API_KEY = old


def test_spam_inline_hashtag_stuffing():
    from radar.spam import looks_like_ad_cheap
    # hashtags glued into text, empty list — should still be caught
    assert looks_like_ad_cheap("крутая подборка #дача#идеи#ремонт#скидки#вб", "user1", []) is True

def test_competitor_word_boundary_no_substring():
    from radar.collector import _matches
    from radar.providers.base import Post
    from radar.models import Brand
    from datetime import datetime, timezone
    import json
    b = Brand(); b.exclusions = json.dumps([]); b.market = "global"
    class P: source="competitor"; label="ВБ"; query="ВБ"
    def post(t, tags=None):
        return Post(post_id="1",platform="tiktok",author="a",followers=0,text=t,
                    hashtags=tags or [],created_at=datetime.now(timezone.utc),
                    likes=0,views=0,comments=0,shares=0)
    # "вб" must NOT match inside "обувь"
    assert _matches(post("красивая обувь на лето"), b, P()) is False
    # but matches as a whole word
    assert _matches(post("заказал в ВБ вчера"), b, P()) is True


def test_follower_floor_small_nonviral():
    from radar.collector import _below_follower_floor
    p = _mk_post("нормальный пост про доставку озон сегодня", views=0); p.followers = 50
    assert _below_follower_floor(p) is True

def test_follower_floor_small_viral_kept():
    from radar.collector import _below_follower_floor
    p = _mk_post("нормальный пост", views=600_000); p.followers = 50
    assert _below_follower_floor(p) is False

def test_follower_floor_unknown_not_penalized():
    from radar.collector import _below_follower_floor
    p = _mk_post("нормальный пост", views=0); p.followers = 0
    assert _below_follower_floor(p) is False

def test_follower_floor_big_account_kept():
    from radar.collector import _below_follower_floor
    p = _mk_post("нормальный пост", views=0); p.followers = 5000
    assert _below_follower_floor(p) is False
