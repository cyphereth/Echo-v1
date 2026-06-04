# Competitor-Comment Opportunities + Feed Quality — Design

**Date:** 2026-06-04
**Status:** Approved

## Overview

Три связанных изменения:
1. **Виральность Instagram + порог** — иностранные посты проходят RU-фильтр по лайкам (≥1500) или просмотрам (≥500k); работает для IG где views=0.
2. **Перехват возможностей** — в комментариях под постами конкурентов/ниши находить «возможности» (обсуждают акцию/цену/недовольство) и черновить перехватывающий ответ от лица клиента, с бейджем в Очереди.
3. **Качество ленты** — дропать посты с >3 хэштегами (обычно спам), кроме вирусных.

## Feature 1 — Virality threshold

`collector.py`:
```python
VIRAL_LIKES = 1500
VIRAL_VIEWS = 500_000

def _is_viral(post) -> bool:
    return (post.likes or 0) >= VIRAL_LIKES or (post.views or 0) >= VIRAL_VIEWS
```
`_passes_language` использует `_is_viral(post)` вместо прямой проверки views. Единое правило для TikTok и Instagram.

## Feature 3 — Hashtag spam filter

`collector.py`:
```python
MAX_HASHTAGS = 3
```
В `_matches`, после языкового фильтра: если `len(post.hashtags) > MAX_HASHTAGS` и НЕ `_is_viral(post)` → `return False`. Вирусные проходят даже с множеством хэштегов.

## Feature 2 — Competitor/niche comment opportunities

### Comment model (models.py)
Новые поля:
- `is_opportunity: Mapped[bool] = mapped_column(Boolean, default=False)`
- `opportunity: Mapped[Optional[str]] = mapped_column(Text)`  # короткая причина

Миграция в `db.py` `_MIGRATIONS["comments"]`:
- `"is_opportunity": "BOOLEAN DEFAULT 0"`
- `"opportunity": "TEXT"`

### Hybrid prefilter (drafts.py or api.py helper)
```python
OPPORTUNITY_TRIGGERS = ["акци", "скидк", "промокод", "цена", "цены", "дорого",
    "где лучше", "посоветуй", "альтернатив", "разочаров", "не совет", "надоел",
    "ужас", "плохо", "верните", "обман"]

def _is_opportunity_candidate(text: str, sentiment: str) -> bool:
    t = text.lower()
    return sentiment == "negative" or any(trig in t for trig in OPPORTUNITY_TRIGGERS)
```

### Claude evaluation (drafts.py)
Новая функция:
```python
def evaluate_opportunity(comment_text, source, competitor, brand_name) -> dict:
    """Returns {is_opportunity: bool, reason: str, reply: str}. {} on no-key/error."""
```
Модель `claude-haiku-4-5-20251001`, max_tokens 250, timeout 60, retry 1 на JSON-ошибку (паттерн как в suggest).
Промпт (ru): «Комментарий под постом {конкурента X / нишевой темы}: "{text}". Это возможность для бренда {brand} нативно зайти и привлечь этого человека? Если да — короткий дружелюбный ненавязчивый ответ от лица {brand} с мягкой выгодой. JSON: {"is_opportunity":false,"reason":"","reply":""}»

### _fetch_and_store_comments (api.py)
Для mention с `source in ("competitor","niche")`:
1. `_is_opportunity_candidate(text, sentiment)` — иначе сохраняем коммент без черновика/возможности
2. Если кандидат и `drafted < MAX_COMMENT_DRAFTS`: `evaluate_opportunity(...)`
3. Если `is_opportunity`: `Comment(draft=reply, is_opportunity=True, opportunity=reason)`, `drafted += 1`
4. Иначе сохраняем без черновика

Для `source == "brand"`: текущая логика (черновик на негатив), `is_opportunity=False`.

### _comment_card (api.py)
Добавить `"is_opportunity": c.is_opportunity`, `"opportunity": c.opportunity`.

## Frontend

### Queue.jsx
- Маппинг комментариев прокидывает `is_opportunity`, `opportunity`.
- Бейдж **«🎯 Возможность»** на карточке где `is_opportunity` (тултип = `opportunity`).
- Кнопка-фильтр **«Только возможности»** рядом с lane-фильтрами: показывает только `is_opportunity` карточки.

### AppPage.jsx mentionToItem
Комментарий-объект включает `is_opportunity`, `opportunity` (из `_comment_card`). (Очередь берёт комментарии из feed items — проверить что поля доходят; comments приходят через getComments в Detail, а Queue строит из feedItems.comments — нужно убедиться что inbox-mention.draft путь несёт opportunity. Если Queue строит из mention-level draft, добавить поля на mention-карточку тоже.)

## Error Handling
- Claude недоступен/битый JSON → `is_opportunity=False`, без черновика, коммент сохраняется. 1 retry.
- Не кандидат → Claude не зовётся.
- Старые данные → миграция ставит `is_opportunity=0`.

## Testing
- `_is_viral`: likes 1500 → True; likes 100, views 600k → True; likes 100 views 100 → False.
- hashtag filter: пост с 5 хэштегами не-вирусный → дроп; вирусный с 5 → проходит.
- `_is_opportunity_candidate`: «у них акция» → True; «спасибо!» → False; негатив → True.
- `evaluate_opportunity` — скип без LLM-ключа (вернёт {}).

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/collector.py` | `_is_viral`, `MAX_HASHTAGS`, hashtag-фильтр в `_matches` |
| `backend/radar/models.py` | Comment.is_opportunity, opportunity |
| `backend/radar/db.py` | миграция comments |
| `backend/radar/drafts.py` | `_is_opportunity_candidate`, `evaluate_opportunity` |
| `backend/radar/api.py` | opportunity-логика в `_fetch_and_store_comments`, `_comment_card` |
| `backend/tests/test_profile_scan.py` | тесты viral/hashtag/opportunity-кандидат |
| `echo-app/src/components/app/Queue.jsx` | бейдж 🎯 + фильтр «Только возможности» |
| `echo-app/src/pages/AppPage.jsx` | проброс is_opportunity/opportunity в comment-объект |
