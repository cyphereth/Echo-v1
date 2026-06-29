"""chat_namespace: единый namespace составного post_id чата для realtime и поллера."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_username_wins_and_normalised():
    from radar.core.providers.telegram import chat_namespace
    assert chat_namespace("@MyGroup", -1001234567890) == "mygroup"
    assert chat_namespace("plainname", None) == "plainname"


def test_username_less_marked_id_unmarked():
    from radar.core.providers.telegram import chat_namespace
    # Telethon marked supergroup/channel id -> unmarked peer id string
    assert chat_namespace(None, -1001234567890) == "1234567890"
    assert chat_namespace("", -1001234567890) == "1234567890"


def test_accepts_string_and_hash_forms():
    from radar.core.providers.telegram import chat_namespace
    assert chat_namespace(None, "-1001234567890") == "1234567890"
    assert chat_namespace(None, "#1234567890") == "1234567890"
    assert chat_namespace(None, 1234567890) == "1234567890"


def test_non_numeric_without_username_returned_as_is():
    from radar.core.providers.telegram import chat_namespace
    # never raises — falls back to the raw string
    assert chat_namespace(None, "chat") == "chat"
