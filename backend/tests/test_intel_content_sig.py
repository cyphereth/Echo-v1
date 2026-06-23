import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_content_sig_collapses_reposts_with_different_footers():
    from radar.intel.aggregate import content_sig
    body = ("Боец закрыл собой 11-летнего ребёнка, в которого летел дрон ВСУ. "
            "В Родинском наш боец Артём с позывным Якут спас ребёнка от FPV-дрона.")
    a = body + " Подписаться на ТБ. https://t.me/tb_news"
    b = body + " Источник: РИА. https://t.me/rian_ru?source=1"
    assert content_sig(a) == content_sig(b), "verbatim reposts must share a signature"


def test_content_sig_differs_for_different_content():
    from radar.intel.aggregate import content_sig
    assert content_sig("ПВО сбила пять ракет над Курском ночью этого дня") != \
           content_sig("Эвакуация мирных жителей продолжается в Донецке сегодня")


def test_content_sig_empty_is_blank():
    from radar.intel.aggregate import content_sig
    assert content_sig("") == ""
    assert content_sig(None) == ""
