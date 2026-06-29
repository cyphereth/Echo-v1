"""Ukrainian detection for auto-translation. The detector must fire on a single
Ukrainian-exclusive letter AND on marker words for short letter-free posts, while
leaving plain Russian alone. See translate.py."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radar.intel import translate


def test_is_ukrainian_single_exclusive_letter():
    assert translate._is_ukrainian("вибухи у Харкові") is True   # і
    assert translate._is_ukrainian("Київ під обстрілом") is True  # ї/і


def test_is_ukrainian_marker_words_without_special_letters():
    # «Загроза … Суми» has no і/ї/є/ґ — caught by the marker word «загроза».
    assert translate._is_ukrainian("Загроза БпЛА. Суми") is True
    assert translate._is_ukrainian("Тривога! Перебувайте в укритті") is True


def test_is_ukrainian_plain_russian_is_not_flagged():
    assert translate._is_ukrainian("Угроза БПЛА. Воронеж, пройдите в укрытие") is False
    assert translate._is_ukrainian("обстрел Белгорода, горит склад") is False


def test_maybe_translate_calls_translator_for_ukrainian(monkeypatch):
    monkeypatch.setattr(translate, "_get_translator",
                        lambda: type("T", (), {"translate": staticmethod(lambda s: "ПЕРЕВОД")})())
    assert translate.maybe_translate("Загроза БпЛА. Суми") == "ПЕРЕВОД"


def test_maybe_translate_skips_russian(monkeypatch):
    # Russian text must not even reach the translator.
    monkeypatch.setattr(translate, "_get_translator",
                        lambda: (_ for _ in ()).throw(AssertionError("should not translate")))
    txt = "Угроза БПЛА. Воронеж"
    assert translate.maybe_translate(txt) == txt
