# backend/tests/test_intel_geo_match.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_matches_simple_city_name():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск", "брянская"], "kursk": ["курск"]}
    assert match_directions("прилет в брянске сегодня", terms) == {"bryansk"}


def test_matches_oblast_adjective():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск", "брянская"]}
    assert match_directions("в Брянской области тихо", terms) == {"bryansk"}


def test_does_not_match_substring_inside_word():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск"], "ryazan": ["рязанский"]}
    # "брянсковый" must NOT match "брянск" (4-letter derivational suffix -овый exceeds the 3-letter inflection cap)
    assert match_directions("брянсковый лес", terms) == set()
    # "рязанский" matches its own word form (whole word, followed by space)
    assert match_directions("рязанский район", terms) == {"ryazan"}


def test_matches_multiple_directions():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск"], "kharkiv": ["харьков"]}
    assert match_directions("обстановка: брянск и харьков", terms) == {"bryansk", "kharkiv"}


def test_case_insensitive_and_cyrillic_aware():
    from radar.intel.geo_match import match_directions
    terms = {"kharkiv": ["харків", "харьков"]}
    assert match_directions("вибух у ХАРКОВІ та Харькове", terms) == {"kharkiv"}


def test_empty_text_returns_empty():
    from radar.intel.geo_match import match_directions
    assert match_directions("", {"bryansk": ["брянск"]}) == set()
