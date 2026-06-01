from datetime import datetime, timedelta
import random

BRANDS = [
    {"id": 1, "name": "PapaPizza", "probes": ["папапицца", "#papapizza", "@papapizza_ru", "papa pizza"]},
    {"id": 2, "name": "CafeBlanche", "probes": ["кафе бланш", "#cafeblanche", "@cafe_blanche"]},
]

_now = datetime.utcnow()

def _dt(minutes_ago: int) -> str:
    return (_now - timedelta(minutes=minutes_ago)).isoformat() + "Z"

RAW_MENTIONS = [
    {
        "id": 1,
        "platform": "instagram",
        "author": "katerina_food",
        "followers": 48200,
        "created_at": _dt(8),
        "text": "Заказала пиццу PapaPizza и это был полный кошмар — курьер опоздал на час, пицца холодная, тесто сырое. Никогда больше! #папапицца #разочарование",
        "severity": 88,
        "phase": "rising",
        "tone": "negative",
        "confidence": 0.91,
        "category": "complaint",
        "lane": "pr",
        "is_hot": True,
        "views": 62000,
        "velocity": 340,
        "draft": "Катерина, нам очень жаль! Это недопустимо. Напишите нам в директ — разберёмся и компенсируем заказ.",
        "draft_flag": None,
        "status": "new",
    },
    {
        "id": 2,
        "platform": "tiktok",
        "author": "foodblogger_msk",
        "followers": 312000,
        "created_at": _dt(23),
        "text": "Честный обзор PapaPizza: тесто на дровяной печи реально крутое, но соус мог бы быть поострее. 7/10 🍕",
        "severity": 42,
        "phase": "fading",
        "tone": "neutral",
        "confidence": 0.78,
        "category": "review",
        "lane": "smm",
        "is_hot": False,
        "views": 28500,
        "velocity": 12,
        "draft": "Спасибо за честный обзор! Острый соус — в меню уже этим летом 🌶️ Следите за обновлениями!",
        "draft_flag": None,
        "status": "new",
    },
    {
        "id": 3,
        "platform": "instagram",
        "author": "misha_reviews",
        "followers": 9800,
        "created_at": _dt(41),
        "text": "папапицца подняли цены уже третий раз за год, при этом порции стали меньше. классика",
        "severity": 71,
        "phase": "rising",
        "tone": "negative",
        "confidence": 0.84,
        "category": "pricing",
        "lane": "pr",
        "is_hot": False,
        "views": 14700,
        "velocity": 65,
        "draft": "Михаил, слышим вас. Цены скорректированы из-за роста стоимости ингредиентов, но мы работаем над тем, чтобы сохранить ценность для гостей.",
        "draft_flag": None,
        "status": "new",
    },
    {
        "id": 4,
        "platform": "tiktok",
        "author": "comedy_ivan",
        "followers": 127000,
        "created_at": _dt(67),
        "text": "PapaPizza vs дошираковая пицца из микроволновки — слепой тест 😂 Результат вас удивит #папапицца #прикол",
        "severity": 31,
        "phase": "peaked",
        "tone": "neutral",
        "confidence": 0.72,
        "category": "humor",
        "lane": "smm",
        "is_hot": False,
        "views": 198000,
        "velocity": -28,
        "draft": "Ахаха, мы оценили 😄 Зато наша пицца без пакетика с приправой! Заходи — угостим настоящей итальянской 🍕",
        "draft_flag": "humor_manual",
        "status": "new",
    },
    {
        "id": 5,
        "platform": "instagram",
        "author": "anna_lifestyle",
        "followers": 23400,
        "created_at": _dt(95),
        "text": "Обожаю папапиццу! Лучшая маргарита в городе, берём каждую пятницу ❤️ #вкусно #пицца #москва",
        "severity": 10,
        "phase": "fading",
        "tone": "positive",
        "confidence": 0.95,
        "category": "praise",
        "lane": "smm",
        "is_hot": False,
        "views": 5200,
        "velocity": 3,
        "draft": "Анна, вы наш любимый гость! 🍕❤️ Каждую пятницу ждём вас — скоро будет сюрприз для постоянных гостей!",
        "draft_flag": None,
        "status": "new",
    },
    {
        "id": 6,
        "platform": "tiktok",
        "author": "food_critic_spb",
        "followers": 89300,
        "created_at": _dt(134),
        "text": "Нашёл волос в пицце @papapizza_ru. Отправил жалобу — проигнорировали. Роспотребнадзор следующий шаг 🤢",
        "severity": 96,
        "phase": "rising",
        "tone": "negative",
        "confidence": 0.97,
        "category": "quality",
        "lane": "pr",
        "is_hot": True,
        "views": 87000,
        "velocity": 520,
        "draft": "Это абсолютно недопустимо и нам очень жаль. Свяжитесь с нами напрямую — мы расследуем ситуацию лично и полностью компенсируем.",
        "draft_flag": None,
        "status": "new",
    },
    {
        "id": 7,
        "platform": "instagram",
        "author": "startup_dima",
        "followers": 3200,
        "created_at": _dt(180),
        "text": "Папапицца открыла доставку в наш район! Теперь не надо ехать через полгорода 🙌",
        "severity": 8,
        "phase": "fading",
        "tone": "positive",
        "confidence": 0.88,
        "category": "praise",
        "lane": "none",
        "is_hot": False,
        "views": 890,
        "velocity": 1,
        "draft": "Ура! Добро пожаловать в семью 🍕 Первый заказ — скидка 15% по промокоду НОВЫЙРАЙОН",
        "draft_flag": None,
        "status": "new",
    },
    {
        "id": 8,
        "platform": "tiktok",
        "author": "blogger_nastya",
        "followers": 445000,
        "created_at": _dt(210),
        "text": "Сравниваю топ-5 пиццерий Москвы. PapaPizza заняла 2 место — не хватило остроты и разнообразия топпингов для первого 🍕",
        "severity": 38,
        "phase": "fading",
        "tone": "neutral",
        "confidence": 0.81,
        "category": "review",
        "lane": "smm",
        "is_hot": False,
        "views": 341000,
        "velocity": -15,
        "draft": "Настя, второе место в Москве — уже круто! 😄 Новые топпинги в меню уже скоро, следи за обновлениями!",
        "draft_flag": None,
        "status": "new",
    },
]

_action_store: dict[int, dict] = {}


def get_mentions(brand_id: int) -> list[dict]:
    base = RAW_MENTIONS if brand_id == 1 else _make_brand2_mentions()
    result = []
    for m in base:
        overrides = _action_store.get(m["id"], {})
        result.append({**m, **overrides})
    return result


def apply_action(mention_id: int, action: str, draft: str | None) -> bool:
    if action == "approve":
        _action_store[mention_id] = {"status": "sent", **({"draft": draft} if draft else {})}
    elif action == "reject":
        _action_store[mention_id] = {"status": "rejected"}
    elif action == "pr":
        _action_store[mention_id] = {"lane": "pr", "status": "new", "draft_flag": None}
    else:
        return False
    return True


def _make_brand2_mentions() -> list[dict]:
    return [
        {
            "id": 101,
            "platform": "instagram",
            "author": "travel_lena",
            "followers": 18900,
            "created_at": _dt(15),
            "text": "Кафе Бланш — уютнейшее место в центре! Круассаны просто таят во рту ☕🥐",
            "severity": 12,
            "phase": "fading",
            "tone": "positive",
            "confidence": 0.93,
            "category": "praise",
            "lane": "smm",
            "is_hot": False,
            "views": 3400,
            "velocity": 5,
            "draft": "Лена, спасибо! Круассаны выпекаем каждое утро свежие 🥐 Ждём вас снова!",
            "draft_flag": None,
            "status": "new",
        },
    ]
