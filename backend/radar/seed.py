"""Seed the DB with realistic demo data on first startup."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from .models import Brand, Probe, Mention, MentionSnapshot
from .scoring import Snapshot, severity, phase

def _now(): return datetime.now(timezone.utc)
def _ago(minutes: int) -> datetime: return _now() - timedelta(minutes=minutes)

def _snap(views, likes, comments, shares) -> dict:
    return dict(views=views, likes=likes, comments=comments, shares=shares)

_SEED = [
    dict(
        platform="instagram", post_id="ig_001", author="katerina_food",
        followers=48200, ago=8,
        text="Заказала пиццу PapaPizza и это был полный кошмар — курьер опоздал на час, пицца холодная, тесто сырое. Никогда больше! #папапицца #разочарование",
        lane="pr", tone="negative", category="complaint", confidence=0.91,
        draft="Катерина, нам очень жаль! Это недопустимо. Напишите нам в директ — разберёмся и компенсируем заказ.",
        snapshots=[_snap(18000,210,48,12), _snap(40000,510,98,34), _snap(62000,890,167,61)],
    ),
    dict(
        platform="tiktok", post_id="tt_002", author="foodblogger_msk",
        followers=312000, ago=23,
        text="Честный обзор PapaPizza: тесто на дровяной печи реально крутое, но соус мог бы быть поострее. 7/10 🍕",
        lane="smm", tone="neutral", category="review", confidence=0.78,
        draft="Спасибо за честный обзор! Острый соус — в меню уже этим летом 🌶️ Следите за обновлениями!",
        snapshots=[_snap(9000,340,62,18), _snap(19000,680,120,41), _snap(28500,1100,198,72)],
    ),
    dict(
        platform="instagram", post_id="ig_003", author="misha_reviews",
        followers=9800, ago=41,
        text="папапицца подняли цены уже третий раз за год, при этом порции стали меньше. классика",
        lane="pr", tone="negative", category="complaint", confidence=0.84,
        draft="Михаил, слышим вас. Цены скорректированы из-за роста стоимости ингредиентов, но мы работаем над тем, чтобы сохранить ценность для гостей.",
        snapshots=[_snap(4200,88,31,7), _snap(9800,190,64,18), _snap(14700,310,98,29)],
    ),
    dict(
        platform="tiktok", post_id="tt_004", author="comedy_ivan",
        followers=127000, ago=67,
        text="PapaPizza vs дошираковая пицца из микроволновки — слепой тест 😂 Результат вас удивит #папапицца #прикол",
        lane="smm", tone="neutral", category="humor", confidence=0.72,
        draft="Ахаха, мы оценили 😄 Зато наша пицца без пакетика с приправой! Заходи — угостим настоящей итальянской 🍕",
        draft_flag="humor_manual",
        snapshots=[_snap(220000,8900,1420,680), _snap(210000,9200,1480,710), _snap(198000,9400,1510,730)],
    ),
    dict(
        platform="instagram", post_id="ig_005", author="anna_lifestyle",
        followers=23400, ago=95,
        text="Обожаю папапиццу! Лучшая маргарита в городе, берём каждую пятницу ❤️ #вкусно #пицца #москва",
        lane="smm", tone="positive", category="positive", confidence=0.95,
        draft="Анна, вы наш любимый гость! 🍕❤️ Каждую пятницу ждём вас — скоро будет сюрприз для постоянных гостей!",
        snapshots=[_snap(1800,62,14,3), _snap(3800,130,28,7), _snap(5200,198,42,11)],
    ),
    dict(
        platform="tiktok", post_id="tt_006", author="food_critic_spb",
        followers=89300, ago=134,
        text="Нашёл волос в пицце @papapizza_ru. Отправил жалобу — игнорируют. Роспотребнадзор следующий шаг 🤢",
        lane="pr", tone="negative", category="viral_negative", confidence=0.97,
        draft="Это абсолютно недопустимо и нам очень жаль. Свяжитесь с нами напрямую — мы расследуем ситуацию лично и полностью компенсируем.",
        snapshots=[_snap(12000,620,340,180), _snap(48000,2800,1200,620), _snap(87000,5100,2200,1100)],
    ),
    dict(
        platform="instagram", post_id="ig_007", author="startup_dima",
        followers=3200, ago=180,
        text="Папапицца открыла доставку в наш район! Теперь не надо ехать через полгорода 🙌",
        lane="smm", tone="positive", category="positive", confidence=0.88,
        draft="Ура! Добро пожаловать в семью 🍕 Первый заказ — скидка 15% по промокоду НОВЫЙРАЙОН",
        snapshots=[_snap(310,18,4,1), _snap(620,38,9,2), _snap(890,58,14,4)],
    ),
    dict(
        platform="tiktok", post_id="tt_008", author="blogger_nastya",
        followers=445000, ago=210,
        text="Сравниваю топ-5 пиццерий Москвы. PapaPizza заняла 2 место — не хватило остроты и разнообразия топпингов для первого 🍕",
        lane="smm", tone="neutral", category="review", confidence=0.81,
        draft="Настя, второе место в Москве — уже круто! 😄 Новые топпинги в меню уже скоро, следи за обновлениями!",
        snapshots=[_snap(180000,7200,980,440), _snap(290000,11000,1580,720), _snap(341000,13200,1890,860)],
    ),
]

_SEED_COMPETITOR = [
    dict(
        platform="tiktok", post_id="cmp_001", author="pizza_wars_ru",
        followers=245000, ago=55, source="competitor", competitor="DoDo Pizza",
        text="DoDo Pizza разочаровала — честный обзор. Тесто пресное, порции маленькие, за эти деньги ожидал большего 😤",
        lane="smm", tone="negative", category="complaint", confidence=0.86,
        opportunity="Аудитория обсуждает DoDo Pizza — момент предложить ваш бренд как альтернативу.",
        draft="Понимаем разочарование 🍕 Если хочется живого теста на дровах — попробуйте PapaPizza, первый заказ со скидкой.",
        snapshots=[_snap(120000,5400,820,310), _snap(240000,11200,1500,640), _snap(312000,18700,2100,910)],
    ),
    dict(
        platform="instagram", post_id="cmp_002", author="eda_review_ru",
        followers=98000, ago=160, source="competitor", competitor="Dominos",
        text="Dominos в 2026 — уже не то. Качество ингредиентов упало, цена выросла. Куда уходить за нормальной пиццей?",
        lane="smm", tone="negative", category="complaint", confidence=0.82,
        opportunity="Аудитория обсуждает Dominos — момент предложить ваш бренд как альтернативу.",
        draft="PapaPizza — живое тесто и итальянские ингредиенты. Доставка за 40 минут, попробуйте 🔥",
        snapshots=[_snap(40000,2100,420,180), _snap(72000,4800,900,360), _snap(94000,7100,1300,520)],
    ),
]

_SEED_NICHE = [
    dict(
        platform="tiktok", post_id="nch_001", author="food_blogger_msk",
        followers=445000, ago=30, source="niche",
        text="Топ-5 пиццерий Москвы 2026 — честный рейтинг. Объездил 12 заведений, рассказываю где реально вкусно 🍕",
        lane="none", tone="neutral", category="review", confidence=0.70,
        opportunity="Тематическая аудитория без упоминания бренда — хороший момент зайти нативно.",
        draft="Огонь подборка! А PapaPizza пробовали? Дровяная печь, живое тесто — будем рады попасть в ваш следующий рейтинг 🍕",
        snapshots=[_snap(220000,12000,2400,1100), _snap(390000,22000,4100,1900), _snap(512000,31000,5200,2400)],
    ),
]

_SEED_BRAND2 = [
    dict(
        platform="instagram", post_id="cb_001", author="travel_lena",
        followers=18900, ago=15,
        text="Кафе Бланш — уютнейшее место в центре! Круассаны просто таят во рту ☕🥐",
        lane="smm", tone="positive", category="positive", confidence=0.93,
        draft="Лена, спасибо! Круассаны выпекаем каждое утро свежие 🥐 Ждём вас снова!",
        snapshots=[_snap(1100,44,9,2), _snap(2400,98,18,5), _snap(3400,148,27,8)],
    ),
    dict(
        platform="tiktok", post_id="cb_002", author="review_nikita",
        followers=34100, ago=90,
        text="Кафе Бланш — цены кусаются, но атмосфера и кофе того стоят. Для свиданий идеально ☕",
        lane="smm", tone="neutral", category="review", confidence=0.76,
        draft="Никита, рады что атмосфера понравилась! Работаем над тем, чтобы ценность соответствовала цене 🙏",
        snapshots=[_snap(3200,180,42,11), _snap(6800,380,88,24), _snap(9600,540,124,34)],
    ),
]

def already_seeded(session: Session) -> bool:
    return session.query(Brand).count() > 0

def run(session: Session) -> None:
    if already_seeded(session):
        return

    # Brand 1
    b1 = Brand(
        name="PapaPizza",
        keywords=json.dumps(["папапицца", "papapizza", "papa pizza"]),
        hashtags=json.dumps(["#папапицца", "#papapizza"]),
        exclusions=json.dumps([]),
        competitors=json.dumps(["DoDo Pizza", "Dominos", "Pizza Hut"]),
        niche_keywords=json.dumps(["доставка пиццы москва", "лучшая пицца"]),
        tone_examples=json.dumps([
            "Очень жаль, что так вышло! Напишите нам — разберёмся.",
            "Рады, что понравилось! Ждём снова 🍕",
        ]),
    )
    session.add(b1)
    session.flush()
    for q in ["папапицца", "#papapizza", "papa pizza"]:
        session.add(Probe(brand_id=b1.id, platform="tiktok", kind="keyword", source="brand", query=q))
    for comp in ["DoDo Pizza", "Dominos", "Pizza Hut"]:
        session.add(Probe(brand_id=b1.id, platform="tiktok", kind="keyword", source="competitor", label=comp, query=comp))
    for term in ["доставка пиццы москва", "лучшая пицца"]:
        session.add(Probe(brand_id=b1.id, platform="tiktok", kind="keyword", source="niche", label=term, query=term))
    session.flush()
    _seed_mentions(session, b1.id, _SEED)
    _seed_mentions(session, b1.id, _SEED_COMPETITOR)
    _seed_mentions(session, b1.id, _SEED_NICHE)

    # Brand 2
    b2 = Brand(
        name="CafeBlanche",
        keywords=json.dumps(["кафе бланш", "cafe blanche", "cafeblanche"]),
        hashtags=json.dumps(["#cafeblanche"]),
        exclusions=json.dumps([]),
        tone_examples=json.dumps([]),
    )
    session.add(b2)
    session.flush()
    session.add(Probe(brand_id=b2.id, platform="instagram", kind="keyword", query="кафе бланш"))
    session.flush()
    _seed_mentions(session, b2.id, _SEED_BRAND2)

    session.commit()

def _seed_mentions(session: Session, brand_id: int, seed_list: list[dict]) -> None:
    for d in seed_list:
        snaps_raw = d.get("snapshots", [])
        snaps_obj = [Snapshot(s["views"], s["likes"], s["comments"], s["shares"]) for s in snaps_raw]
        is_neg    = d.get("tone") == "negative"
        sev       = severity(snaps_obj, followers=d["followers"], is_negative=is_neg)
        ph        = phase(snaps_obj)
        is_hot    = sev >= 50 and ph != "declining"
        m = Mention(
            brand_id=brand_id,
            platform=d["platform"],
            post_id=d["post_id"],
            author=d["author"],
            followers=d["followers"],
            text=d["text"],
            hashtags=json.dumps([]),
            created_at=_ago(d["ago"]),
            likes=snaps_raw[-1]["likes"] if snaps_raw else 0,
            views=snaps_raw[-1]["views"] if snaps_raw else 0,
            comments=snaps_raw[-1]["comments"] if snaps_raw else 0,
            shares=snaps_raw[-1]["shares"] if snaps_raw else 0,
            severity=sev,
            phase=ph,
            tone=d.get("tone", "neutral"),
            is_hot=is_hot,
            category=d.get("category"),
            lane=d.get("lane"),
            source=d.get("source", "brand"),
            competitor=d.get("competitor"),
            opportunity=d.get("opportunity"),
            confidence=d.get("confidence"),
            draft=d.get("draft"),
            draft_flag=d.get("draft_flag"),
            status="new",
        )
        session.add(m)
        session.flush()
        base_ts = _ago(d["ago"])
        for i, s in enumerate(snaps_raw):
            session.add(MentionSnapshot(
                mention_id=m.id,
                ts=base_ts + timedelta(minutes=i * 30),
                **s,
            ))
