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
