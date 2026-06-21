import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import radar.brand.api as api
from radar.core.providers.socialcrawl import SocialCrawlProvider
from radar.core.providers.tikhub import TikHubProvider
from radar.core.providers.mock import MockProvider

# _get_provider() picks a provider from module-level token globals, in priority
# order SocialCrawl → TikHub → Mock. These tests pin those globals via monkeypatch
# (no network: every provider constructor only stores config).


def test_prefers_socialcrawl_when_token_set(monkeypatch):
    monkeypatch.setattr(api, "SOCIALCRAWL_TOKEN", "sc_test")
    monkeypatch.setattr(api, "TIKHUB_TOKEN", "tikhub_test")
    assert isinstance(api._get_provider(), SocialCrawlProvider)


def test_falls_back_to_tikhub_when_no_socialcrawl(monkeypatch):
    monkeypatch.setattr(api, "SOCIALCRAWL_TOKEN", "")
    monkeypatch.setattr(api, "TIKHUB_TOKEN", "tikhub_test")
    assert isinstance(api._get_provider(), TikHubProvider)


def test_falls_back_to_mock_when_no_tokens(monkeypatch):
    monkeypatch.setattr(api, "SOCIALCRAWL_TOKEN", "")
    monkeypatch.setattr(api, "TIKHUB_TOKEN", "")
    assert isinstance(api._get_provider(), MockProvider)
