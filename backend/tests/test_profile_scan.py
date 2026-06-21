import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from radar.brand.api import _parse_handle


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
    import radar.brand.api as brand_api
    from radar.core.providers.mock import MockProvider
    monkeypatch.setattr(brand_api, "_get_provider", lambda: MockProvider())

    class FakeUser:
        id = 1
    body = brand_api.ScanBody(tiktok="@testbrand", instagram="")
    result = brand_api.profile_scan(body, user=FakeUser())
    assert result["scanned"]["tiktok"] is True
    assert result["name"]
    assert "audience_sentiment" in result


# ── RU/CIS language filter ────────────────────────────────────────────────────

def _mk_post(text, views=0):
    from radar.core.providers.base import Post
    from datetime import datetime, timezone
    return Post(post_id="1", platform="tiktok", author="a", followers=0,
                text=text, hashtags=[], created_at=datetime.now(timezone.utc),
                likes=0, views=views, comments=0, shares=0)

def _mk_brand(market):
    from radar.models import Brand
    b = Brand(); b.market = market; return b

def test_lang_ru_keeps_cyrillic():
    from radar.brand.collector import _passes_language
    assert _passes_language(_mk_post("купил на озоне, отлично"), _mk_brand("ru")) is True

def test_lang_ru_drops_foreign():
    from radar.brand.collector import _passes_language
    assert _passes_language(_mk_post("amazing delivery, loved it"), _mk_brand("ru")) is False

def test_lang_ru_keeps_viral_foreign():
    from radar.brand.collector import _passes_language
    assert _passes_language(_mk_post("amazing delivery", views=600_000), _mk_brand("ru")) is True

def test_lang_global_keeps_everything():
    from radar.brand.collector import _passes_language
    assert _passes_language(_mk_post("amazing delivery"), _mk_brand("global")) is True


# ── Viral threshold + hashtag spam ────────────────────────────────────────────

def test_is_viral_by_likes():
    from radar.brand.collector import _is_viral
    assert _is_viral(_mk_post("x", views=0)) is False
    p = _mk_post("x"); p.likes = 1500
    assert _is_viral(p) is True

def test_is_viral_by_views():
    from radar.brand.collector import _is_viral
    assert _is_viral(_mk_post("x", views=600_000)) is True

# ── Opportunity prefilter ─────────────────────────────────────────────────────

def test_opportunity_candidate_trigger():
    from radar.brand.drafts import _is_opportunity_candidate
    assert _is_opportunity_candidate("у них скоро акция и скидки", "neutral") is True

def test_opportunity_candidate_negative():
    from radar.brand.drafts import _is_opportunity_candidate
    assert _is_opportunity_candidate("всё дорого и плохо", "negative") is True

def test_opportunity_candidate_noise():
    from radar.brand.drafts import _is_opportunity_candidate
    assert _is_opportunity_candidate("спасибо, классное видео", "positive") is False


def test_min_text_len_is_20():
    from radar.brand.collector import MIN_TEXT_LEN
    assert MIN_TEXT_LEN == 20


# ── Ad / spam cheap rules ─────────────────────────────────────────────────────

def test_spam_seller_username():
    from radar.core.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("классная штука для дома и кухни каждый день", "wb_goldy", []) is True

def test_spam_too_short():
    from radar.core.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("огонь", "user1", []) is True

def test_spam_real_post_passes():
    from radar.core.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("заказал на озоне, доставили за два дня, всё отлично", "katya_msk", ["озон"]) is False

def test_cheap_ignores_marketplace_phrase():
    # "промокод"/"артикул" are sphere-specific noise now judged by the AI, not the cheap layer
    from radar.core.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("заказал по промокоду в тануки, ролл огонь", "katya_msk", []) is False

def test_cheap_allows_long_caption():
    from radar.core.spam import looks_like_ad_cheap
    long_caption = "Сегодня заехали в новый ресторан японской кухни, " * 5  # ~250 chars, normal
    assert looks_like_ad_cheap(long_caption, "foodie_anna", []) is False

def test_cheap_allows_many_hashtags():
    # food/lifestyle posts routinely use >3 hashtags — not junk by itself
    from radar.core.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap(
        "обалденные роллы в тануки сегодня", "user_masha",
        ["суши", "роллы", "японскаякухня", "вкусно", "доставка", "ужин"]) is False

def test_cheap_allows_inline_hashtags():
    from radar.core.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("крутая подборка роллов #суши#роллы#еда#доставка#ужин", "user1", []) is False

def test_classify_ads_batch_no_key():
    from radar.core.spam import classify_ads_batch
    import radar.core.spam as sp
    old = sp.LLM_API_KEY; sp.LLM_API_KEY = ""
    try:
        assert classify_ads_batch(["a", "b", "c"]) == [False, False, False]
    finally:
        sp.LLM_API_KEY = old


def test_competitor_word_boundary_no_substring():
    from radar.brand.collector import _matches
    from radar.core.providers.base import Post
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
    from radar.brand.collector import _below_follower_floor
    p = _mk_post("нормальный пост про доставку озон сегодня", views=0); p.followers = 50
    assert _below_follower_floor(p) is True

def test_follower_floor_small_viral_kept():
    from radar.brand.collector import _below_follower_floor
    p = _mk_post("нормальный пост", views=600_000); p.followers = 50
    assert _below_follower_floor(p) is False

def test_follower_floor_unknown_not_penalized():
    from radar.brand.collector import _below_follower_floor
    p = _mk_post("нормальный пост", views=0); p.followers = 0
    assert _below_follower_floor(p) is False

def test_follower_floor_big_account_kept():
    from radar.brand.collector import _below_follower_floor
    p = _mk_post("нормальный пост", views=0); p.followers = 5000
    assert _below_follower_floor(p) is False


def test_rebuild_probes_geo_and_category():
    import json
    from radar.core import db
    from radar.models import Brand
    from radar.brand.models import BrandProbe
    from radar.brand.api import _rebuild_probes
    s = db.get_session()
    b = Brand(name="TestSalon", user_id=1,
              keywords=json.dumps(["мой салон"]),
              competitors=json.dumps(["Конкурент1"]),
              niche_keywords=json.dumps(["маникюр"]),
              category_terms=json.dumps(["салон красоты"]),
              geo="Москва")
    s.add(b); s.flush()
    _rebuild_probes(s, b)
    probes = s.query(BrandProbe).filter_by(brand_id=b.id).all()
    q = {(p.source, p.query) for p in probes}
    # brand & named competitor: no city
    assert ("brand", "мой салон") in q
    assert ("competitor", "Конкурент1") in q
    # category (competitor source) & niche: city appended
    assert ("competitor", "салон красоты Москва") in q
    assert ("niche", "маникюр Москва") in q
    # cleanup
    s.query(BrandProbe).filter_by(brand_id=b.id).delete()
    s.delete(b); s.commit()

def test_rebuild_probes_no_geo():
    import json
    from radar.core import db
    from radar.models import Brand
    from radar.brand.models import BrandProbe
    from radar.brand.api import _rebuild_probes
    s = db.get_session()
    b = Brand(name="Fed", user_id=1, keywords=json.dumps(["бренд"]),
              competitors=json.dumps([]), niche_keywords=json.dumps(["тема"]),
              category_terms=json.dumps([]), geo="")
    s.add(b); s.flush()
    _rebuild_probes(s, b)
    q = {(p.source, p.query) for p in s.query(BrandProbe).filter_by(brand_id=b.id).all()}
    assert ("niche", "тема") in q  # no city appended
    s.query(BrandProbe).filter_by(brand_id=b.id).delete(); s.delete(b); s.commit()


def test_geo_probe_requires_city():
    from radar.brand.collector import _matches
    from radar.core.providers.base import Post
    from radar.models import Brand
    from datetime import datetime, timezone
    import json
    b = Brand(); b.exclusions = json.dumps([]); b.market = "ru"
    class P: source="niche"; label="маникюр"; query="маникюр Казань"
    def post(t):
        return Post(post_id="1",platform="tiktok",author="a",followers=500,text=t,
                    hashtags=[],created_at=datetime.now(timezone.utc),
                    likes=0,views=0,comments=0,shares=0)
    # has term but NOT city → geo probe rejects
    assert _matches(post("красивый маникюр сегодня делала"), b, P()) is False
    # has both term and city → matches
    assert _matches(post("маникюр в Казань салон"), b, P()) is True


def test_follower_floor_off_in_local_mode():
    from radar.brand.collector import _below_follower_floor
    p = _mk_post("обычный городской пост про красоту", views=0); p.followers = 50
    assert _below_follower_floor(p, local_mode=True) is False
    assert _below_follower_floor(p, local_mode=False) is True

def test_local_mode_audience_probes():
    import json
    from radar.core import db
    from radar.models import Brand
    from radar.brand.models import BrandProbe
    from radar.brand.api import _rebuild_probes
    s = db.get_session()
    b = Brand(name="Salon2", user_id=1, keywords=json.dumps(["мой салон"]),
              competitors=json.dumps([]), niche_keywords=json.dumps([]),
              category_terms=json.dumps([]), audience_terms=json.dumps(["женское","мода"]),
              geo="Казань", local_mode=True)
    s.add(b); s.flush()
    _rebuild_probes(s, b)
    q = {(p.source, p.query) for p in s.query(BrandProbe).filter_by(brand_id=b.id).all()}
    assert ("niche", "женское Казань") in q
    assert ("niche", "мода Казань") in q
    s.query(BrandProbe).filter_by(brand_id=b.id).delete(); s.delete(b); s.commit()

def test_local_mode_off_no_audience_probes():
    import json
    from radar.core import db
    from radar.models import Brand
    from radar.brand.models import BrandProbe
    from radar.brand.api import _rebuild_probes
    s = db.get_session()
    b = Brand(name="Fed2", user_id=1, keywords=json.dumps(["б"]),
              competitors=json.dumps([]), niche_keywords=json.dumps([]),
              category_terms=json.dumps([]), audience_terms=json.dumps(["женское"]),
              geo="Казань", local_mode=False)
    s.add(b); s.flush()
    _rebuild_probes(s, b)
    q = {p.query for p in s.query(BrandProbe).filter_by(brand_id=b.id).all()}
    assert "женское Казань" not in q
    s.query(BrandProbe).filter_by(brand_id=b.id).delete(); s.delete(b); s.commit()


def test_provider_by_handle():
    from radar.core.spam import looks_like_provider_cheap
    assert looks_like_provider_cheap("красивый дизайн сегодня", "aiva.nails") is True
    assert looks_like_provider_cheap("работаем для вас", "kazan_brows_studio") is True

def test_provider_by_phrase():
    from radar.core.spam import looks_like_provider_cheap
    assert looks_like_provider_cheap("свободные окошки на завтра, запись в директ", "anna_k") is True

def test_client_not_provider():
    from radar.core.spam import looks_like_provider_cheap
    assert looks_like_provider_cheap("когда лето чувствуется не только на улице", "lu_happy13") is False

def test_tgk_not_provider_signal():
    from radar.core.spam import looks_like_provider_cheap
    # тгк link alone should not flag a regular person as provider
    assert looks_like_provider_cheap("мой тгк: мойканал, заходите", "vasya_petrov") is False

def test_classify_providers_no_key():
    import radar.core.spam as sp
    old = sp.LLM_API_KEY; sp.LLM_API_KEY = ""
    try:
        from radar.core.spam import classify_providers_batch
        assert classify_providers_batch(["a","b"]) == [False, False]
    finally:
        sp.LLM_API_KEY = old


def test_provider_handle_no_substring_collision():
    from radar.core.spam import looks_like_provider_cheap
    # "nail" inside the patronymic "Наилевна" must NOT flag a provider
    assert looks_like_provider_cheap("ценить каждый момент", "leilanailevna.ph") is False
    # but a real nail handle does
    assert looks_like_provider_cheap("дизайн", "aiva.nails") is True


# ── suggest_brand: response parsing ───────────────────────────────────────────

def test_extract_suggest_json_single_text_block():
    from radar.brand.api import _extract_suggest_json
    blocks = [{"type": "text", "text": '{"keywords": ["ozon"]}'}]
    assert _extract_suggest_json(blocks) == {"keywords": ["ozon"]}

def test_extract_suggest_json_takes_last_text_block():
    from radar.brand.api import _extract_suggest_json
    blocks = [
        {"type": "text", "text": "Let me search for this brand."},
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "ozon"}},
        {"type": "web_search_tool_result", "content": [{"title": "Ozon"}]},
        {"type": "text", "text": '{"keywords": ["ozon", "озон"], "competitors": ["wildberries"]}'},
    ]
    assert _extract_suggest_json(blocks) == {
        "keywords": ["ozon", "озон"], "competitors": ["wildberries"]}

def test_extract_suggest_json_strips_markdown_fence():
    from radar.brand.api import _extract_suggest_json
    blocks = [{"type": "text", "text": '```json\n{"keywords": ["x"]}\n```'}]
    assert _extract_suggest_json(blocks) == {"keywords": ["x"]}

def test_extract_suggest_json_no_text_raises():
    import pytest
    from radar.brand.api import _extract_suggest_json
    with pytest.raises(ValueError):
        _extract_suggest_json([{"type": "web_search_tool_result", "content": []}])


# ── suggest_brand: request payload ────────────────────────────────────────────

def test_build_suggest_payload_has_web_search_tool():
    from radar.brand.api import _build_suggest_payload
    p = _build_suggest_payload("Ozon")
    tools = p["tools"]
    assert any(t.get("type") == "web_search_20250305" for t in tools)

def test_build_suggest_payload_large_token_budget():
    from radar.brand.api import _build_suggest_payload
    p = _build_suggest_payload("Ozon")
    assert p["max_tokens"] >= 4000

def test_build_suggest_payload_includes_brand_name():
    from radar.brand.api import _build_suggest_payload
    p = _build_suggest_payload("CafeBlanche")
    user_msg = p["messages"][0]["content"]
    assert "CafeBlanche" in user_msg

def test_build_suggest_payload_asks_for_many_keywords():
    from radar.brand.api import _build_suggest_payload
    p = _build_suggest_payload("Ozon")
    user_msg = p["messages"][0]["content"]
    assert "20-30" in user_msg


# ── suggest_brand: transient retry ────────────────────────────────────────────

def _httpx_status_error(code):
    import httpx
    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)

def test_is_transient_parse_and_value_errors():
    import json as _json
    from radar.brand.api import _is_transient_suggest_error
    assert _is_transient_suggest_error(ValueError("x")) is True
    assert _is_transient_suggest_error(KeyError("x")) is True
    assert _is_transient_suggest_error(_json.JSONDecodeError("e", "", 0)) is True

def test_is_transient_network_error():
    import httpx
    from radar.brand.api import _is_transient_suggest_error
    assert _is_transient_suggest_error(httpx.TimeoutException("t")) is True
    assert _is_transient_suggest_error(httpx.ConnectError("c")) is True

def test_is_transient_http_status():
    from radar.brand.api import _is_transient_suggest_error
    assert _is_transient_suggest_error(_httpx_status_error(503)) is True
    assert _is_transient_suggest_error(_httpx_status_error(429)) is True
    assert _is_transient_suggest_error(_httpx_status_error(400)) is False

def test_is_transient_other_false():
    from radar.brand.api import _is_transient_suggest_error
    assert _is_transient_suggest_error(RuntimeError("nope")) is False

def test_suggest_with_retry_succeeds_after_transient():
    from radar.brand.api import _suggest_with_retry
    calls = {"n": 0}
    def call():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("empty body")
        return {"ok": True}
    assert _suggest_with_retry(call, attempts=3) == {"ok": True}
    assert calls["n"] == 3

def test_suggest_with_retry_exhausts_and_raises_last():
    import pytest
    from radar.brand.api import _suggest_with_retry
    def call():
        raise ValueError("still bad")
    with pytest.raises(ValueError):
        _suggest_with_retry(call, attempts=2)

def test_suggest_with_retry_non_transient_raises_immediately():
    import pytest
    from radar.brand.api import _suggest_with_retry
    calls = {"n": 0}
    def call():
        calls["n"] += 1
        raise RuntimeError("fatal")
    with pytest.raises(RuntimeError):
        _suggest_with_retry(call, attempts=3)
    assert calls["n"] == 1  # non-transient → no retry


# ── sphere-aware ad classifier payload ────────────────────────────────────────

def test_build_ads_payload_includes_sphere():
    from radar.core.spam import _build_ads_classify_payload
    p = _build_ads_classify_payload(["текст про роллы"], sphere="сеть японских ресторанов")
    assert "сеть японских ресторанов" in p["system"]

def test_build_ads_payload_includes_texts():
    from radar.core.spam import _build_ads_classify_payload
    p = _build_ads_classify_payload(["уникальный_маркер_текста"], sphere="")
    assert "уникальный_маркер_текста" in p["messages"][0]["content"]

def test_build_ads_payload_no_sphere_ok():
    from radar.core.spam import _build_ads_classify_payload
    p = _build_ads_classify_payload(["a", "b"], sphere="")
    assert p["model"] == "claude-haiku-4-5-20251001"
    assert isinstance(p["max_tokens"], int) and p["max_tokens"] > 0


# ── brand-name guaranteed in keywords ─────────────────────────────────────────

def test_ensure_name_prepends_when_missing():
    from radar.brand.api import _ensure_name_in_keywords
    assert _ensure_name_in_keywords("Тануки", ["суши", "роллы"]) == ["Тануки", "суши", "роллы"]

def test_ensure_name_noop_when_present_substring_ci():
    from radar.brand.api import _ensure_name_in_keywords
    # already covered (case-insensitive substring) → unchanged
    assert _ensure_name_in_keywords("Самокат", ["самокат доставка", "еда"]) == ["самокат доставка", "еда"]

def test_ensure_name_empty_name_noop():
    from radar.brand.api import _ensure_name_in_keywords
    assert _ensure_name_in_keywords("", ["суши"]) == ["суши"]
    assert _ensure_name_in_keywords("   ", ["суши"]) == ["суши"]


# ── pipeline: brand-lane disambiguation ───────────────────────────────────────

def test_brand_lane_disambiguated_not_ad_judged(monkeypatch):
    """Brand-lane mentions go through disambiguation (off-topic homonyms hidden,
    real ones kept), NOT the ad/noise judge; niche lane still uses the noise judge."""
    from datetime import datetime, timezone
    import radar.core.spam as spam
    import radar.brand.pipeline as pipeline
    from radar.core import db
    from radar.models import Brand
    from radar.brand.models import BrandMention
    # noise judge would hide everything if (wrongly) applied to the brand lane
    monkeypatch.setattr(spam, "classify_ads_batch", lambda texts, sphere="": [True] * len(texts))
    # disambiguation: first brand text off-topic, second on-topic
    monkeypatch.setattr(spam, "disambiguate_brand_batch",
                        lambda texts, brand_name, sphere="": [True, False][:len(texts)])
    monkeypatch.setattr(pipeline, "generate_draft", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "rescore_mention", lambda *a, **k: None)
    s = db.get_session()
    b = Brand(name="Тануки", user_id=1, keywords='["тануки"]', sphere="суши-рестораны")
    s.add(b); s.flush()

    def mk(src, pid, txt):
        m = BrandMention(brand_id=b.id, platform="tiktok", post_id=pid, author="a",
                         text=txt, source=src, is_spam=False,
                         created_at=datetime.now(timezone.utc),
                         first_seen=datetime.now(timezone.utc))
        s.add(m); return m
    brand_off = mk("brand", "d-off", "прошёл уровень за тануки в игре сегодня")
    brand_on  = mk("brand", "d-on", "ужинали в тануки, роллы супер")
    niche_m   = mk("niche", "d-niche", "вообще про суши где-то в мире")
    s.flush()

    pipeline.classify_and_draft(s, b.id)
    s.refresh(brand_off); s.refresh(brand_on); s.refresh(niche_m)
    try:
        assert brand_off.is_spam is True    # off-topic homonym hidden
        assert brand_on.is_spam is False    # real brand mention kept
        assert niche_m.is_spam is True      # niche judged as noise
    finally:
        s.query(BrandMention).filter_by(brand_id=b.id).delete()
        s.delete(b); s.commit()


# ── brand-lane disambiguation ─────────────────────────────────────────────────

def test_build_disambiguate_payload_includes_brand_and_sphere():
    from radar.core.spam import _build_disambiguate_payload
    p = _build_disambiguate_payload(["пост про #tanuki в игре"], brand_name="Тануки",
                                    sphere="сеть японских ресторанов")
    blob = p["system"] + p["messages"][0]["content"]
    assert "Тануки" in blob
    assert "сеть японских ресторанов" in blob
    assert "пост про #tanuki в игре" in blob

def test_disambiguate_brand_batch_fail_open_no_key():
    import radar.core.spam as sp
    old = sp.LLM_API_KEY; sp.LLM_API_KEY = ""
    try:
        from radar.core.spam import disambiguate_brand_batch
        assert disambiguate_brand_batch(["a", "b"], "Тануки", "еда") == [False, False]
    finally:
        sp.LLM_API_KEY = old

def test_disambiguate_brand_batch_empty():
    from radar.core.spam import disambiguate_brand_batch
    assert disambiguate_brand_batch([], "Тануки", "еда") == []


# ── intent reach ──────────────────────────────────────────────────────────────

def test_looks_like_intent_true():
    from radar.brand.pipeline import _looks_like_intent
    assert _looks_like_intent("посоветуйте, где вкусно поесть?") is True
    assert _looks_like_intent("куда сходить на выходных?") is True

def test_looks_like_intent_false():
    from radar.brand.pipeline import _looks_like_intent
    assert _looks_like_intent("купил роллы вчера, очень вкусно") is False
    assert _looks_like_intent("просто красивое видео про суши") is False

def test_opportunity_niche_intent_vs_plain():
    from radar.brand.pipeline import opportunity_for
    from radar.brand.models import BrandMention
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    intent = BrandMention(brand_id=1, platform="tiktok", post_id="i1", author="a",
                          source="niche", text="подскажите, куда сходить поесть?",
                          created_at=now, first_seen=now)
    plain  = BrandMention(brand_id=1, platform="tiktok", post_id="i2", author="a",
                          source="niche", text="люблю японскую кухню",
                          created_at=now, first_seen=now)
    o_intent = opportunity_for(intent)
    o_plain  = opportunity_for(plain)
    assert "рекомендацию" in o_intent  # stronger intent hint (sphere-neutral copy)
    assert o_intent != o_plain
    assert o_plain is not None         # plain niche keeps the existing hint

def test_opportunity_competitor_unchanged():
    from radar.brand.pipeline import opportunity_for
    from radar.brand.models import BrandMention
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    m = BrandMention(brand_id=1, platform="tiktok", post_id="c1", author="a",
                     source="competitor", competitor="Якитория", text="был в якитории",
                     created_at=now, first_seen=now)
    assert "Якитория" in opportunity_for(m)
