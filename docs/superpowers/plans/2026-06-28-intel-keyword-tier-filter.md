# Tier-фильтр ключевых слов intel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ввести вес (tier) strong/weak у терминов словаря intel, чтобы пост впускался в ленту по 1 strong-совпадению, либо 2+ weak, либо 1 weak + гео — срезав мусор из 39% постов, впущенных одним многозначным словом.

**Architecture:** Колонка `tier` в `intel_lexicon` (значения `strong`/`weak`, дефолт `weak`); разметка хранится в `keywords.seed.json` (tier категории + точечные overrides в `_meta`) и грузится в БД через `intake.ingest_lexicon_json` на каждом старте. Фильтр `keyword_relevant()` переписан под новое правило и получает `geo_hit` от `detect_place()`. Словарь грузится в `collect_probe`/`realtime` как `dict {term: tier}` вместо списка терминов.

**Tech Stack:** Python 3, SQLAlchemy (SQLite), pytest. Бэкенд в `backend/`, запуск тестов из `backend/`.

## Global Constraints

- Ни одно существующее слово из `keywords.seed.json` не удаляется — только добавляются tier-пометки и новые термины.
- Правило впуска: **1 strong ИЛИ 2+ weak ИЛИ (1 weak + гео-метка)**.
- Дефолтный tier для незаданного термина = `weak`.
- Аббревиатуры из `collector.ABBREVIATIONS` считаются `strong`.
- Куратор-keywords (`spam_filter.load_keywords`, `kind="keyword"`) не меняются — остаются мгновенным впуском, bypass length-gate.
- Только вперёд: существующие записи `intel_mentions` не трогаются, ретро-чистки нет.
- Погодный guard (`AMBIGUOUS_WEATHER_TERMS` + `_looks_like_weather`) сохраняется.
- iCloud-репозиторий: коммит-шаги стейджат файлы **по имени** (никаких `git add -A`/`git add .`).
- Тесты запускаются из каталога `backend/`: `cd backend && python -m pytest ...`.

---

### Task 1: Колонка `tier` в `intel_lexicon`

**Files:**
- Modify: `backend/radar/intel/models.py:106-112` (модель `IntelLexicon`)
- Modify: `backend/radar/core/db.py:32-` (словарь `_MIGRATIONS`)
- Test: `backend/tests/test_intel_lexicon_tier.py` (создать)

**Interfaces:**
- Produces: `IntelLexicon.tier` — `Mapped[str]`, NOT NULL, default `"weak"`. Колонка существует в БД после `init_db()`/`_migrate()`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_intel_lexicon_tier.py`:

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa – registers IntelLexicon
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_lexicon_row_defaults_to_weak_tier():
    from radar.intel.models import IntelLexicon
    s = _sess()
    row = IntelLexicon(term="что-то", meaning="", category="x")
    s.add(row)
    s.commit()
    fetched = s.query(IntelLexicon).filter_by(term="что-то").one()
    assert fetched.tier == "weak"


def test_lexicon_tier_can_be_strong():
    from radar.intel.models import IntelLexicon
    s = _sess()
    s.add(IntelLexicon(term="калибр", meaning="", category="x", tier="strong"))
    s.commit()
    assert s.query(IntelLexicon).filter_by(term="калибр").one().tier == "strong"
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py -v`
Expected: FAIL — `TypeError: 'tier' is an invalid keyword argument for IntelLexicon` (поля ещё нет).

- [ ] **Step 3: Добавить поле в модель**

В `backend/radar/intel/models.py` в классе `IntelLexicon` после строки `category:` добавить:

```python
    tier:       Mapped[str]      = mapped_column(Text, nullable=False, default="weak")
```

Итоговый класс:

```python
class IntelLexicon(Base):
    __tablename__ = "intel_lexicon"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    term:       Mapped[str]      = mapped_column(Text, unique=True, nullable=False)
    meaning:    Mapped[str]      = mapped_column(Text, default="")
    category:   Mapped[Optional[str]] = mapped_column(Text)
    tier:       Mapped[str]      = mapped_column(Text, nullable=False, default="weak")
    created_at: Mapped[datetime] = mapped_column(default=_now)
```

- [ ] **Step 4: Добавить запись в `_MIGRATIONS`**

В `backend/radar/core/db.py` в словарь `_MIGRATIONS` добавить новый ключ (рядом с другими `intel_*`):

```python
    "intel_lexicon": {
        "tier": "TEXT NOT NULL DEFAULT 'weak'",
    },
```

Это нужно, чтобы на уже существующей БД (`echo_radar.db`) колонка добавилась через ALTER на старте — `create_all()` существующую таблицу не трогает.

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/models.py backend/radar/core/db.py backend/tests/test_intel_lexicon_tier.py
git commit -m "feat(intel): колонка tier в intel_lexicon (default weak)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `intake` пишет tier из категории и overrides

**Files:**
- Modify: `backend/radar/intel/intake.py:55-94` (`ingest_lexicon_json`)
- Test: `backend/tests/test_intel_lexicon_tier.py` (дополнить)

**Interfaces:**
- Consumes: `IntelLexicon.tier` (Task 1).
- Produces: `ingest_lexicon_json(session, path)` дополнительно вычисляет tier каждого термина по правилу: `overrides_strong` → `strong`; `overrides_weak` → `weak`; иначе `tier` категории; иначе `weak`. Записывает его в `intel_lexicon.tier` на обеих ветках insert/update. Возвращаемый dict `{"added", "updated"}` не меняется.

- [ ] **Step 1: Написать падающий тест**

Дополнить `backend/tests/test_intel_lexicon_tier.py`:

```python
def _write_seed(tmp_path):
    import json
    data = {
        "_meta": {
            "overrides_weak": ["работа"],
            "overrides_strong": ["сирена"],
        },
        "missiles_weapons": {"description": "оружие", "tier": "strong",
                             "words": ["калибр", "работа"]},
        "alerts_status":    {"description": "тревоги", "tier": "weak",
                             "words": ["опасность", "сирена"]},
    }
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_ingest_assigns_tier_from_category(tmp_path):
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    ingest_lexicon_json(s, _write_seed(tmp_path))
    # strong-категория → strong
    assert s.query(IntelLexicon).filter_by(term="калибр").one().tier == "strong"
    # weak-категория → weak
    assert s.query(IntelLexicon).filter_by(term="опасность").one().tier == "weak"


def test_ingest_applies_overrides(tmp_path):
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    ingest_lexicon_json(s, _write_seed(tmp_path))
    # overrides_weak бьёт strong-категорию
    assert s.query(IntelLexicon).filter_by(term="работа").one().tier == "weak"
    # overrides_strong бьёт weak-категорию
    assert s.query(IntelLexicon).filter_by(term="сирена").one().tier == "strong"


def test_ingest_updates_tier_on_reingest(tmp_path):
    """Повторный ингест меняет tier у существующей строки, не плодит дубли."""
    import json
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    seed = _write_seed(tmp_path)
    ingest_lexicon_json(s, seed)
    # переписать seed: калибр теперь в weak-категории без override
    data = {"_meta": {}, "misc": {"description": "x", "tier": "weak", "words": ["калибр"]}}
    import pathlib
    pathlib.Path(seed).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ingest_lexicon_json(s, seed)
    rows = s.query(IntelLexicon).filter_by(term="калибр").all()
    assert len(rows) == 1
    assert rows[0].tier == "weak"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py -k "tier_from_category or overrides or updates_tier" -v`
Expected: FAIL — `калибр` получает дефолт `weak` (intake ещё не читает tier), а override-ассертов не проходит.

- [ ] **Step 3: Реализовать чтение tier в `ingest_lexicon_json`**

Заменить тело `ingest_lexicon_json` в `backend/radar/intel/intake.py` (строки 73-94) на:

```python
    added = updated = 0
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    meta = data.get("_meta", {})
    overrides_weak = {w.strip().lower() for w in meta.get("overrides_weak", [])}
    overrides_strong = {w.strip().lower() for w in meta.get("overrides_strong", [])}

    def _tier_for(term: str, category_tier: str) -> str:
        if term in overrides_strong:
            return "strong"
        if term in overrides_weak:
            return "weak"
        return category_tier

    for category, obj in data.items():
        if category == "_meta":
            continue
        if not isinstance(obj, dict):
            continue
        meaning = obj.get("description", "")
        category_tier = obj.get("tier", "weak")
        for word in obj.get("words", []):
            term = word.strip().lower()
            if not term:
                continue
            tier = _tier_for(term, category_tier)
            row = session.query(IntelLexicon).filter_by(term=term).first()
            if row is None:
                session.add(IntelLexicon(term=term, meaning=meaning,
                                         category=category, tier=tier))
                added += 1
            else:
                row.meaning, row.category, row.tier = meaning, category, tier
                updated += 1
    session.commit()
    return {"added": added, "updated": updated}
```

Также обновить docstring: добавить строку, что tier берётся из `tier` категории с учётом `_meta.overrides_weak`/`overrides_strong`, дефолт `weak`.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Регресс — старый intake-тест не сломан**

Run: `cd backend && python -m pytest tests/test_intel_intake.py tests/test_intel_keyword_filter.py::test_ingest_lexicon_json -v`
Expected: PASS (категории без `tier` дают дефолт `weak`, добавленный аргумент не ломает round-trip).

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/intake.py backend/tests/test_intel_lexicon_tier.py
git commit -m "feat(intel): intake проставляет tier из категории и overrides

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Разметка tier существующих 424 терминов в seed

**Files:**
- Modify: `backend/radar/intel/data/keywords.seed.json` (добавить `tier` каждой категории + `_meta.overrides_weak`/`overrides_strong`)
- Test: `backend/tests/test_intel_lexicon_tier.py` (дополнить — round-trip реального seed)

**Interfaces:**
- Consumes: `ingest_lexicon_json` с поддержкой tier (Task 2).
- Produces: реальный seed размечен; известные термины получают ожидаемый tier.

- [ ] **Step 1: Написать падающий тест на реальном seed**

Дополнить `backend/tests/test_intel_lexicon_tier.py`:

```python
_REAL_SEED = os.path.join(
    os.path.dirname(__file__), "..", "radar", "intel", "data", "keywords.seed.json"
)


def test_real_seed_tiers():
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    ingest_lexicon_json(s, _REAL_SEED)

    def tier(term):
        row = s.query(IntelLexicon).filter_by(term=term).first()
        assert row is not None, f"term {term!r} missing from seed"
        return row.tier

    # сильные узкие термины
    for t in ("калибр", "вибух", "прилёт", "пво", "шахед"):
        assert tier(t) == "strong", f"{t} expected strong, got {tier(t)}"
    # слабые многозначные (генераторы мусора)
    for t in ("сейчас", "внимание", "движение", "очередь", "работа", "слышно"):
        assert tier(t) == "weak", f"{t} expected weak, got {tier(t)}"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py::test_real_seed_tiers -v`
Expected: FAIL — без разметки `сейчас`/`движение`/`очередь` (категории `time_markers`/`alerts_status`/`explosions_sounds`) дают неверный tier.

- [ ] **Step 3: Разметить категории в seed**

В `backend/radar/intel/data/keywords.seed.json` каждой категории (объекту с `words`) добавить поле `"tier"` рядом с `"description"`:

| категория | tier |
|---|---|
| `missiles_weapons` | `"strong"` |
| `drones_uav` | `"strong"` |
| `explosions_sounds` | `"strong"` |
| `air_defense_intercept` | `"strong"` |
| `consequences` | `"strong"` |
| `ukrainian` | `"strong"` |
| `alerts_status` | `"weak"` |
| `visual_effects` | `"weak"` |
| `movement_direction` | `"weak"` |
| `time_markers` | `"weak"` |

Пример (для одной категории):

```json
  "missiles_weapons": {
    "description": "...",
    "tier": "strong",
    "words": [ ... без изменений ... ]
  },
```

**Списки `words` не трогать** — порядок и состав сохраняются.

- [ ] **Step 4: Добавить overrides в `_meta`**

В объект `_meta` файла добавить два ключа:

```json
    "overrides_weak": [
      "работа", "работают", "работали", "отработал", "отработало", "отработали",
      "очередь", "очередями", "одиночные", "слышно", "громко", "мопед", "жужжит",
      "бах", "бабах", "бам", "бум", "тук", "тукнуло", "стук", "щёлк", "щелк", "летают",
      "пострадавших", "жертв", "без света", "без электричества", "обесточен",
      "свет моргает", "связь пропала",
      "удар", "вогонь", "дим", "димить", "гул", "гуло", "гуде", "свист",
      "летить", "летять", "пролітає", "небезпека", "повітряна", "повітряні",
      "фламинго", "самолет", "вертолет", "вертолёт", "орёл", "барс"
    ],
    "overrides_strong": [
      "сирена", "сирены", "воздушная тревога", "воздушні тривоги",
      "ракетная опасность", "ракетная атака", "ракетный удар",
      "угроза с воздуха", "обстрел", "артобстрел"
    ]
```

(`overrides_weak` гасит ложняковые слова из strong-категорий и омонимы-названия из `drones_uav`; `overrides_strong` поднимает однозначные алармы из weak-категории `alerts_status`.)

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py -v`
Expected: PASS (включая `test_real_seed_tiers`).

- [ ] **Step 6: Проверить, что JSON валиден и слова не потеряны**

Run: `cd backend && python -c "import json; d=json.load(open('radar/intel/data/keywords.seed.json')); print(sum(len(v.get('words',[])) for k,v in d.items() if k!='_meta'), 'word entries'); print('cats:', [k for k in d if k!='_meta'])"`
Expected: то же число word-entries, что и до правки (≥461), и все 10 категорий на месте.

- [ ] **Step 7: Коммит**

```bash
git add backend/radar/intel/data/keywords.seed.json backend/tests/test_intel_lexicon_tier.py
git commit -m "feat(intel): разметка tier strong/weak для словаря (слова не удалены)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Tier-логика фильтра — `matched_terms` / `keyword_relevant` / `chat_message_relevant`

**Files:**
- Modify: `backend/radar/intel/collector.py:119-191` (`matched_terms`, `keyword_relevant`, `chat_message_relevant`) + добавить `load_lexicon_tiers` и `_geo_hit`
- Modify: `backend/tests/test_intel_keyword_filter.py` (обновить вызовы под dict-сигнатуру)
- Test: `backend/tests/test_intel_keyword_filter.py` (дополнить tier-матрицей)

**Interfaces:**
- Consumes: `IntelLexicon.tier` (Task 1); `radar.intel.geo.detect_place(text) -> tuple[str|None, str|None]`.
- Produces:
  - `load_lexicon_tiers(session) -> dict[str, str]` — `{term_lower: tier}`.
  - `matched_terms(text, lexicon_tiers) -> list[tuple[str, str]]` — пары `(term_lower, tier)`; аббревиатуры → `"strong"`.
  - `keyword_relevant(text, lexicon_tiers, geo_hit=False) -> bool`.
  - `chat_message_relevant(text, author, lexicon_tiers=(), keywords=(), geo_hit=False) -> bool`.
  - `_geo_hit(text) -> bool`.

- [ ] **Step 1: Написать падающие тесты tier-матрицы**

Дополнить `backend/tests/test_intel_keyword_filter.py`:

```python
def test_keyword_relevant_tier_rule():
    from radar.intel.collector import keyword_relevant
    strong_only = {"шахед": "strong"}
    weak_only   = {"сейчас": "weak", "работа": "weak"}

    # 1 strong → впуск
    assert keyword_relevant("летит шахед", strong_only) is True
    # 1 weak без гео → отбой
    assert keyword_relevant("прямо сейчас отвечу", weak_only) is False
    # 2 weak → впуск
    assert keyword_relevant("сейчас работа кипит", weak_only) is True
    # 1 weak + гео → впуск
    assert keyword_relevant("сейчас в Белгороде", weak_only, geo_hit=True) is True
    # 0 совпадений → отбой
    assert keyword_relevant("обычный текст", weak_only) is False


def test_keyword_relevant_weather_guard_kept():
    from radar.intel.collector import keyword_relevant
    lex = {"град": "strong"}
    # «град» в погодном контексте — не впуск даже как strong
    assert keyword_relevant("завтра ожидается град и гроза, прогноз погоды", lex) is False
    # «град» без погодного контекста — strong впуск
    assert keyword_relevant("по позициям отработал град", lex) is True


def test_matched_terms_returns_tiers():
    from radar.intel.collector import matched_terms
    out = matched_terms("выпустили калибр", {"калибр": "strong"})
    assert ("калибр", "strong") in out


def test_matched_terms_abbrev_is_strong():
    from radar.intel.collector import matched_terms
    out = matched_terms("замечен БПЛА над городом", {})
    assert ("БПЛА", "strong") in out
```

- [ ] **Step 2: Обновить существующие вызовы в тесте под dict-сигнатуру**

В `backend/tests/test_intel_keyword_filter.py` существующие unit-вызовы `keyword_relevant(...)` со списком терминов заменить на dict со `strong` (старое поведение «1 термин → впуск» = strong). Например:

```python
# было: keyword_relevant("выпустили калибр", ["калибр"])  → стало:
assert keyword_relevant("выпустили калибр", {"калибр": "strong"}) is True
assert keyword_relevant("бои под Суджей", {}) is False
assert keyword_relevant("обычная погода завтра", {"калибр": "strong"}) is False
assert keyword_relevant("некалибрный шуруп", {"калибр": "strong"}) is False
assert keyword_relevant("попал storm shadow точно в цель", {"storm shadow": "strong"}) is True
```

Аналогично заменить вызовы `chat_message_relevant(text, author, [...], (...))` на dict первым лексикон-аргументом: `chat_message_relevant(text, author, {"term": "strong"}, (...))`. Пройтись по всему файлу и привести каждый вызов `keyword_relevant`/`chat_message_relevant`/`matched_terms` к dict-форме.

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_intel_keyword_filter.py -v`
Expected: FAIL — `matched_terms`/`keyword_relevant` ещё работают по-старому (список, нет tier/geo_hit), новые тесты и сигнатуры не сходятся.

- [ ] **Step 4: Переписать функции в `collector.py`**

Заменить `matched_terms` (строки 119-132) на:

```python
def matched_terms(text: str, lexicon_tiers) -> list[tuple[str, str]]:
    """(term, tier) pairs appearing in text at a word boundary.

    Two passes: (1) the word-lexicon (mapping term→tier), lowercased/case-insensitive;
    (2) the uppercase ABBREVIATIONS, matched case-sensitively against the ORIGINAL text
    and always tier "strong" (they are narrow military markers).
    """
    raw = (text or "").strip()
    low = raw.lower()
    out: list[tuple[str, str]] = []
    for term, tier in dict(lexicon_tiers).items():
        if re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", low):
            out.append((term.lower(), tier or "weak"))
    for ab in _ABBREV_RE.findall(raw):
        out.append((ab, "strong"))
    return out
```

Заменить `keyword_relevant` (строки 140-156) на:

```python
def keyword_relevant(text: str, lexicon_tiers, geo_hit: bool = False) -> bool:
    """Return True if text passes the tiered admission rule.

    Rule: 1 strong OR 2+ weak OR (1 weak + geo_hit). KEYWORD-ONLY: geo alone is NOT an
    admit path — geo only PROMOTES a single weak hit (geo_hit is computed by the caller
    via detect_place). The ``lexicon_tiers`` mapping is loaded once per collect_probe.

    Weather false-positive guard: if every matched term is an ambiguous weather word
    (град/смерч/торнадо) AND the text reads like a weather report, drop it.
    """
    hits = matched_terms(text, lexicon_tiers)
    if not hits:
        return False
    non_weather = [t for (t, _tier) in hits if t not in AMBIGUOUS_WEATHER_TERMS]
    if not non_weather and _looks_like_weather(text):
        return False
    strong = [t for (t, tier) in hits if tier == "strong"]
    weak = [t for (t, tier) in hits if tier == "weak"]
    if strong:
        return True
    if len(weak) >= 2:
        return True
    if len(weak) == 1 and geo_hit:
        return True
    return False
```

Заменить сигнатуру и последнюю строку `chat_message_relevant` (строки 159-191):

```python
def chat_message_relevant(text: str, author: str, lexicon_tiers=(),
                          keywords: tuple = (), geo_hit: bool = False) -> bool:
```

и в конце функции (строка 191):

```python
    return kw_hit or keyword_relevant(stripped, lexicon_tiers, geo_hit=geo_hit)
```

Добавить два хелпера рядом с `keyword_relevant` (например, после неё):

```python
def load_lexicon_tiers(session) -> dict[str, str]:
    """Term→tier map for the admission gate. One query, loaded once per collect cycle."""
    from .models import IntelLexicon
    return {
        (t or "").lower(): (tier or "weak")
        for (t, tier) in session.query(IntelLexicon.term, IntelLexicon.tier).all()
    }


def _geo_hit(text: str) -> bool:
    """True if the text names any tracked oblast/city (promotes a single weak hit)."""
    from .geo import detect_place
    key, city = detect_place(text)
    return bool(key or city)
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_intel_keyword_filter.py -v`
Expected: PASS (старые, обновлённые и новые tier-тесты).

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/collector.py backend/tests/test_intel_keyword_filter.py
git commit -m "feat(intel): tier-правило впуска в keyword_relevant (+ geo promote)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Проводка `collect_probe` и `realtime` под tier + geo_hit

**Files:**
- Modify: `backend/radar/intel/collector.py:244-353` (`collect_probe`)
- Modify: `backend/radar/intel/realtime.py:83-114,200,246,316` (`store_realtime_post` + загрузка словаря)
- Test: `backend/tests/test_intel_keyword_filter.py` (channel collect_probe — уже есть; дополнить случай weak-одиночки)

**Interfaces:**
- Consumes: `load_lexicon_tiers`, `keyword_relevant(text, lexicon_tiers, geo_hit)`, `chat_message_relevant(..., geo_hit)`, `_geo_hit` (Task 4).
- Produces: оба пути сбора (поллер и realtime) применяют tier-правило.

- [ ] **Step 1: Написать падающий тест на поведение поллера**

Дополнить `backend/tests/test_intel_keyword_filter.py` (рядом с существующим channel-тестом). Тест проверяет, что одиночное weak-слово без гео НЕ сохраняется, а strong — сохраняется. Использует реальный seed (после Task 3) и фейковый provider:

```python
def test_collect_probe_drops_single_weak(monkeypatch):
    from radar.intel import collector
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelMention, IntelProbe
    from radar.intel.seed import ensure_default_directions
    s = _sess()
    ensure_default_directions(s)
    ingest_lexicon_json(s, _SEED_PATH)

    probe = IntelProbe(query="@t", platform="telegram", side="ru",
                       kind="channel", watermark=None)
    s.add(probe); s.commit()

    def _post(pid, text):
        return SimpleNamespace(post_id=pid, text=text, author="a",
                               created_at=datetime.now(timezone.utc),
                               url=None, likes=0, reply_to_tg_id=None, media=None)

    # один weak («сейчас»), без гео и без второго термина — должен отсеяться;
    # strong («прилёт») — пройти.
    page = SimpleNamespace(posts=[
        _post("1", "прямо сейчас расскажу новость про погоду экономику"),
        _post("2", "прилёт по складу, есть разрушения"),
    ])
    monkeypatch.setattr(probe_provider := SimpleNamespace(), "search",
                        lambda *a, **k: page, raising=False)
    monkeypatch.setattr(probe_provider, "search_chat",
                        lambda *a, **k: [], raising=False)

    collector.collect_probe(s, probe, probe_provider)
    texts = [m.text for m in s.query(IntelMention).all()]
    assert any("прилёт" in t for t in texts), "strong post must be stored"
    assert not any("расскажу новость" in t for t in texts), "single weak must be dropped"
```

> Исполнителю: если фабрика провайдера/страницы в существующих тестах оформлена иначе — переиспользуй её паттерн (см. соседний channel-тест в этом файле), сохранив суть проверки (strong хранится, одиночный weak — нет).

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_intel_keyword_filter.py::test_collect_probe_drops_single_weak -v`
Expected: FAIL — сейчас `collect_probe` грузит список терминов и впускает «сейчас» как одиночку.

- [ ] **Step 3: Провести `collect_probe`**

В `backend/radar/intel/collector.py`:

Строка 246 — заменить загрузку списка на tier-карту:

```python
        lexicon_tiers = load_lexicon_tiers(session)
        if not lexicon_tiers:
            log.warning("intel lexicon is empty — channel posts kept only on geo match (run lexicon seed)")
```

Везде ниже в функции заменить переменную `lexicon_terms` на `lexicon_tiers`:

- chat-ветка, строка 283:
  ```python
                if not chat_message_relevant(text, author, lexicon_tiers, keywords,
                                             geo_hit=_geo_hit(text)):
                    continue
  ```
- channel-ветка, строка 353:
  ```python
                        if not keyword_relevant(text, lexicon_tiers, geo_hit=_geo_hit(text)):
                            continue
  ```

(Комментарий на строке 245 про «lexicon_terms» обновить на «lexicon_tiers».)

- [ ] **Step 4: Провести `realtime`**

В `backend/radar/intel/realtime.py`:

- Строки 200 и 246 — заменить загрузку:
  ```python
            from .collector import load_lexicon_tiers
            self._lexicon = load_lexicon_tiers(session)
  ```
  (`self._lexicon` теперь dict; имя поля сохраняем.)
- Сигнатура `store_realtime_post` (строка 83): переименовать параметр `lexicon_terms` → `lexicon_tiers` для ясности и прокинуть geo_hit:
  ```python
  def store_realtime_post(session, post, side, kind, lexicon_tiers,
                          spam_words=None, spam_examples=None, keywords=None,
                          subject=None, src_direction_id=None) -> bool:
  ```
- Внутри (строки 102-114) — добавить `geo_hit` и заменить имя:
  ```python
      from .collector import _geo_hit
      geo_hit = _geo_hit(text)
      if kind == "chat":
          if not chat_message_relevant(text, author, lexicon_tiers, keywords or (),
                                       geo_hit=geo_hit):
              return False
      else:
          kw_hit = blocked_by_word(text, keywords or ())
          if not kw_hit:
              clean = " ".join(w for w in text.split() if not w.startswith("#")).strip()
              if len(clean) < MIN_TEXT_LEN:
                  return False
              if not keyword_relevant(text, lexicon_tiers, geo_hit=geo_hit):
                  return False
  ```
- Вызов `store_realtime_post(...)` на строке 316 не требует изменений (передаётся `self._lexicon`, теперь dict).
- Обновить docstring на строке 10 (упоминание `lexicon_terms`).

- [ ] **Step 5: Запустить целевой и регресс-тесты**

Run: `cd backend && python -m pytest tests/test_intel_keyword_filter.py tests/test_intel_collector.py tests/test_intel_realtime.py tests/test_intel_collect_tagging.py -v`
Expected: PASS. Если в realtime/collector тестах есть прямые вызовы `store_realtime_post`/`collect_probe` со списком лексикона — привести лексикон-аргумент к dict-форме `{term: "strong"}` (минимальная правка теста под новую сигнатуру).

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/collector.py backend/radar/intel/realtime.py backend/tests/test_intel_keyword_filter.py
git commit -m "feat(intel): collect_probe и realtime используют tier-карту + geo_hit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Расширение словаря (КАБ/ФАБ, баллистика, морские дроны, инфраструктура)

**Files:**
- Modify: `backend/radar/intel/data/keywords.seed.json` (новые категории + термины)
- Test: `backend/tests/test_intel_lexicon_tier.py` (дополнить — новые термины и их tier)

**Interfaces:**
- Consumes: tier-разметка и ingest (Tasks 2-3).
- Produces: новые термины в словаре с корректным tier.

- [ ] **Step 1: Написать падающий тест на новые термины**

Дополнить `backend/tests/test_intel_lexicon_tier.py`:

```python
def test_seed_expansion_terms():
    from radar.intel.intake import ingest_lexicon_json
    from radar.intel.models import IntelLexicon
    s = _sess()
    ingest_lexicon_json(s, _REAL_SEED)

    def tier(term):
        row = s.query(IntelLexicon).filter_by(term=term).first()
        assert row is not None, f"new term {term!r} missing"
        return row.tier

    # КАБ/ФАБ — strong
    for t in ("каб", "фаб", "фаб-1500", "управляемая авиабомба"):
        assert tier(t) == "strong", f"{t} expected strong"
    # баллистика — strong
    assert tier("баллистическая") == "strong"
    # морские дроны — strong
    assert tier("магура") == "strong"
    # инфраструктура — weak (обычно с другим термином)
    assert tier("нпз") == "weak"
    # массированность — weak
    assert tier("массированный") == "weak"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py::test_seed_expansion_terms -v`
Expected: FAIL — новых терминов в словаре пока нет.

- [ ] **Step 3: Добавить новые категории и термины в seed**

В `backend/radar/intel/data/keywords.seed.json` добавить новые категории (объекты с `tier` + `words`) и дополнить существующие:

Новые категории:

```json
  "guided_bombs": {
    "description": "КАБ / управляемые и планирующие авиабомбы",
    "tier": "strong",
    "words": ["каб", "фаб", "фаб-250", "фаб-500", "фаб-1500", "фаб-3000",
              "управляемая авиабомба", "планирующая бомба", "авиабомба",
              "керована авіабомба"]
  },
  "naval_drones": {
    "description": "Морские безэкипажные катера / надводные дроны",
    "tier": "strong",
    "words": ["магура", "magura", "сафари", "морской дрон", "надводный дрон",
              "безэкипажный катер", "морський дрон"]
  },
  "infrastructure": {
    "description": "Объекты энергетики и инфраструктуры (обычно в связке)",
    "tier": "weak",
    "words": ["нпз", "нефтебаза", "подстанция", "тэц", "тэс", "гэс",
              "трансформатор", "нефтеперерабатывающий", "енергооб'єкт"]
  }
```

Дополнить существующие категории (добавить слова в их массивы `words`, ничего не удаляя):

- `missiles_weapons` (+strong): `баллистика`, `баллистическая`, `гиперзвук`, `квазибаллистическая`, `аэробаллистическая`, `балістика`.
- `drones_uav` (+ омонимы/приманки): `гербера`, `герань-3`, `реактивный шахед`, `италмас`. Затем добавить `гербера`, `италмас` в `_meta.overrides_weak` (категория strong, но это приманки/неоднозначные) — `герань-3` и `реактивный шахед` оставить strong.
- `alerts_status` (+weak, категория уже weak): `массированный`, `массированная атака`, `комбинированный удар`, `массований`.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_intel_lexicon_tier.py -v`
Expected: PASS (включая `test_seed_expansion_terms` и прежние tier-тесты).

- [ ] **Step 5: Проверить валидность JSON**

Run: `cd backend && python -c "import json; d=json.load(open('radar/intel/data/keywords.seed.json')); print('cats:', len([k for k in d if k!='_meta'])); print('words:', sum(len(v.get('words',[])) for k,v in d.items() if k!='_meta'))"`
Expected: 13 категорий, число word-entries выросло на ~40 относительно Task 3.

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/data/keywords.seed.json backend/tests/test_intel_lexicon_tier.py
git commit -m "feat(intel): новые термины словаря — КАБ/ФАБ, баллистика, морские дроны, инфраструктура

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Регресс-замер фильтра по реальной БД (разовый скрипт, не блокирует)

**Files:**
- Create: `backend/scripts/measure_tier_filter.py`

**Interfaces:**
- Consumes: новая tier-логика (`keyword_relevant`, `load_lexicon_tiers`, `_geo_hit`).

- [ ] **Step 1: Написать скрипт-замер**

Создать `backend/scripts/measure_tier_filter.py`:

```python
"""Разовый замер: сколько постов из БД прошло бы новое tier-правило.

Запуск: cd backend && python scripts/measure_tier_filter.py
Печатает: всего постов, прошло (admit), отсеяно (drop), доля отсева.
НИЧЕГО не меняет в БД — только читает.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.core.db import get_session
from radar.intel.collector import load_lexicon_tiers, keyword_relevant, _geo_hit


def main():
    with get_session() as s:
        tiers = load_lexicon_tiers(s)
        rows = s.execute(
            __import__("sqlalchemy").text("select text from intel_mentions where text is not null")
        ).fetchall()
    total = len(rows)
    admit = sum(1 for (t,) in rows if keyword_relevant(t, tiers, geo_hit=_geo_hit(t)))
    drop = total - admit
    print(f"total={total}  admit={admit}  drop={drop}  drop%={100*drop/max(total,1):.1f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Запустить скрипт**

Run: `cd backend && python scripts/measure_tier_filter.py`
Expected: печатает строку вида `total=32558 admit=... drop=... drop%=...`. Ожидаемо drop% заметный (значимая доля прежних одиночек), без ошибок. Это диагностика, а не тест — результат фиксируем в отчёте.

- [ ] **Step 3: Коммит**

```bash
git add backend/scripts/measure_tier_filter.py
git commit -m "chore(intel): скрипт регресс-замера tier-фильтра (read-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Колонка `tier` + миграция → Task 1 ✓
- Разметка seed (категория + overrides) → Tasks 2-3 ✓
- Загрузка tier в БД (`intake`) → Task 2 ✓
- Правило впуска (1 strong / 2+ weak / 1 weak+гео) → Task 4 ✓
- Погодный guard сохранён → Task 4 (тест `test_keyword_relevant_weather_guard_kept`) ✓
- Аббревиатуры = strong → Task 4 ✓
- Куратор-keywords без изменений → Task 4 (ветка `kw_hit` нетронута) ✓
- Проводка `collect_probe` + `realtime` → Task 5 ✓
- Расширение словаря → Task 6 ✓
- Регресс-замер → Task 7 ✓
- Только вперёд (без ретро-чистки) → нигде не трогаем `intel_mentions` ✓

**Type consistency:** `lexicon_tiers: dict[str,str]` единообразно во всех функциях; `matched_terms` → `list[tuple[str,str]]`; `keyword_relevant(text, lexicon_tiers, geo_hit=False)`, `chat_message_relevant(..., geo_hit=False)` совпадают между объявлением (Task 4) и вызовами (Task 5). `load_lexicon_tiers`/`_geo_hit` объявлены в Task 4, используются в Task 5.
