import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from radar.explore import normalize_city, build_city_queries


def test_normalize_city_lowercase_trim():
    assert normalize_city("  Москва ") == ("москва", "москва")


def test_normalize_city_hashtag_strips_space_and_hyphen():
    assert normalize_city("Санкт-Петербург") == ("санкт-петербург", "санктпетербург")


def test_build_city_queries_shape():
    qs = build_city_queries("Москва")
    assert ("tiktok", "keyword", "Москва") in qs
    assert ("tiktok", "keyword", "куда сходить Москва") in qs
    assert ("tiktok", "keyword", "что попробовать Москва") in qs
    assert ("instagram", "hashtag", "москва") in qs
    assert len(qs) == 4
