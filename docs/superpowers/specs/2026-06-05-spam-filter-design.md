# Feed Quality — Ad/Spam Filter — Design

**Date:** 2026-06-05
**Status:** Approved

## Problem

Лента забита рекламой продавцов и дропшипперами, которые набивают бренд-хэштеги (#озон, #wb), вместо живых постов людей. Клиенту нужны: живые обсуждения (отзывы, вопросы, мемы, сравнения) + проблемы/негатив/возможности. Мусор: продавцы, реклама, дропшипперы, накрутка хэштегов.

## Decisions

- Полезный контент = живые обсуждения людей + проблемы/возможности.
- Спам = 4 сигнала: фразы-продаж (A), ник-продавец (B), рекламный тон (C), хэштег-накрутка (D).
- Детект = гибрид: дешёвые правила (A/B/D) + Claude-классификатор тона (C), **батчами**.
- Охват: посты И комментарии.
- Хранение: **store-but-hide** — спам сохраняется с `is_spam=True`, прячется из ленты/очереди, виден с `?include_hidden=1`.
- Длина: 20–150 символов (включая хэштеги) → вне диапазона = спам.
- Язык: иностранный не-вирусный для ru-бренда остаётся **жёстким дропом** (не спам, а нерелевантный рынок).

## New module: backend/radar/spam.py

```python
SALES_PHRASES = ["артикул в профил", "артикул в опис", "ссылка в шапк", "ссылка в профил",
    "пиши в директ", "заказать тут", "заказать здесь", "промокод", "скидка по ссылк",
    "оптом", "доставка по росси", "в наличии", "закажи", "купить со скидк", "по ссылке в",
    "артикул:", "арт.", "цена:", "наш магазин", "переходи по"]

SELLER_NAME_HINTS = ["shop", "store", "magazin", "магазин", "opt", "опт", "artikul",
    "market", "_wb", "wb_", "_ozon", "ozon_", "sale", "skidk"]

def looks_like_ad_cheap(text: str, author: str, hashtags: list[str], min_len=20, max_len=150) -> bool:
    """Level-1 rules: phrases, seller usernames, hashtag stuffing, length. No network."""
    t = (text or "").lower()
    full_len = len(text or "")
    if full_len < min_len or full_len > max_len:
        return True
    if any(p in t for p in SALES_PHRASES):
        return True
    a = (author or "").lower()
    if any(h in a for h in SELLER_NAME_HINTS):
        return True
    if len(hashtags or []) > 3:
        return True
    return False

def classify_ads_batch(texts: list[str]) -> list[bool]:
    """Level-2: Claude decides human vs ad per text in one batched call.
    Returns is_ad flags aligned to input. All-False on no key/error (fail-open)."""
```
`classify_ads_batch`: модель `claude-haiku-4-5-20251001`, промпт — пронумерованный список текстов, Claude возвращает JSON-массив `[{"i":0,"is_ad":true},...]`. max_tokens пропорционально. retry 1. Без `LLM_API_KEY` → `[False]*len`. Размер пачки ≤ 15.

## Models / migration

- `Mention.is_spam: bool = False`
- `Comment.is_spam: bool = False`
- `db.py` `_MIGRATIONS`: `mentions.is_spam = "BOOLEAN DEFAULT 0"`, `comments.is_spam = "BOOLEAN DEFAULT 0"`.

## collector.py

- В `collect_probe`, для поста прошедшего `_matches` (language hard-drop остаётся): вычислить `spam = looks_like_ad_cheap(post.text, post.author, post.hashtags)`. Сохранить mention с `is_spam=spam`. Если spam — НЕ добавлять snapshot и не считать в `count` (не триггерит pipeline-объём), но строка в БД есть.
- Удалить старые «тихие» дропы по длине/хэштегам из `_matches` (теперь это spam-флаг, не drop). Язык остаётся drop.

Helper в collector: после upsert `mention.is_spam = spam`.

## pipeline.py

`classify_and_draft`: выбирать только `is_spam == False` mentions для классификации. Перед классификацией — `classify_ads_batch` по текстам новых не-спам mentions; кого Claude пометил рекламой → `is_spam=True`, исключить из черновиков. Затем обычная классификация+черновики по оставшимся.

## api.py

- `_fetch_and_store_comments`: для каждого коммента `looks_like_ad_cheap` → `is_spam=True` (сохранить, без черновика). Выжившие батчем через `classify_ads_batch` → реклама `is_spam=True`. Только не-спам идут в opportunity/draft.
- `/inbox`: добавить `include_hidden: int = 0`; по умолчанию `filter(Mention.is_spam.is_(False))`.
- `/opportunities`: исключать `Comment.is_spam`.
- `/mentions/{id}/comments`: исключать `is_spam` по умолчанию, `?include_hidden=1` показывает.
- `_comment_card` / `_mention_card`: можно отдавать `is_spam` (для отладки).

## Tests (backend/tests/test_profile_scan.py)

- `looks_like_ad_cheap`: «артикул в профиле …(>20ch)» → True; ник `wb_goldy` → True; живой отзыв 20–150 → False; 8 хэштегов → True; 12 символов → True; 200 символов → True.
- `classify_ads_batch` без ключа → all False.

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/spam.py` | НОВЫЙ: правила + Claude батч |
| `backend/radar/models.py` | Mention.is_spam, Comment.is_spam |
| `backend/radar/db.py` | миграции is_spam |
| `backend/radar/collector.py` | spam-флаг вместо тихих дропов (кроме языка) |
| `backend/radar/pipeline.py` | батч-классификация рекламы, скип спама |
| `backend/radar/api.py` | comments spam-filter, inbox/opportunities/comments исключают спам |
| `backend/tests/test_profile_scan.py` | тесты spam |
