import sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radar.core.providers.socialcrawl import _parse_post, _parse_comment
from radar.core.providers.base import Post, Comment

# Real response shapes observed from socialcrawl.dev /v1/tiktok/search and
# /v1/tiktok/post/comments (envelope already unwrapped to data.items[i]).

_SEARCH_ITEM = {
    "post": {
        "id": "7050251175874071810",
        "url": "https://www.tiktok.com/@alekseynazarov76/video/7050251175874071810",
        "content": {"text": "Ответ пользователю #миллионалыхроз классно", "media_urls": "https://x"},
        "author": {"username": "alekseynazarov76", "display_name": "ПЕРВЫЙ", "verified": False},
        "engagement": {"views": 123835, "likes": 2123, "comments": 56, "shares": 287, "saves": 190},
        "published_at": 1641514522,
    },
    "computed": {"engagement_rate": 0.0199, "language": "ru"},
}

_COMMENT_ITEM = {
    "comment": {
        "id": "7617966234130744065",
        "post_id": "7050251175874071810",
        "text": "А у этой девочки лучше получилось!",
        "author": {"username": "user3745177338140", "display_name": "svetlana"},
        "engagement": {"likes": 7, "replies": 0},
        "published_at": 1773696010,
    },
}


def test_parse_post_maps_core_fields():
    p = _parse_post(_SEARCH_ITEM)
    assert isinstance(p, Post)
    assert p.post_id == "7050251175874071810"
    assert p.platform == "tiktok"
    assert p.author == "alekseynazarov76"
    assert p.text.startswith("Ответ пользователю")
    assert p.likes == 2123 and p.views == 123835
    assert p.comments == 56 and p.shares == 287


def test_parse_post_extracts_hashtags_from_text():
    p = _parse_post(_SEARCH_ITEM)
    assert "миллионалыхроз" in p.hashtags


def test_parse_post_published_at_to_utc_datetime():
    p = _parse_post(_SEARCH_ITEM)
    assert isinstance(p.created_at, datetime)
    assert p.created_at.tzinfo is not None
    assert p.created_at == datetime.fromtimestamp(1641514522, tz=timezone.utc)


def test_parse_post_detects_instagram_by_url():
    item = {"post": dict(_SEARCH_ITEM["post"], url="https://www.instagram.com/p/ABC123/")}
    assert _parse_post(item).platform == "instagram"


def test_parse_post_survives_missing_engagement():
    item = {"post": {"id": "1", "url": "https://www.tiktok.com/@x/video/1",
                     "content": {"text": "hi"}, "author": {"username": "x"}}}
    p = _parse_post(item)
    assert p.likes == 0 and p.views == 0 and p.comments == 0 and p.shares == 0


def test_parse_comment_maps_core_fields():
    c = _parse_comment(_COMMENT_ITEM)
    assert isinstance(c, Comment)
    assert c.comment_id == "7617966234130744065"
    assert c.author == "user3745177338140"
    assert c.text.startswith("А у этой")
    assert c.likes == 7
    assert c.created_at == datetime.fromtimestamp(1773696010, tz=timezone.utc)


def test_parse_comment_survives_missing_engagement():
    c = _parse_comment({"comment": {"id": "9", "text": "x", "author": {"username": "u"}}})
    assert c.likes == 0 and c.comment_id == "9"
