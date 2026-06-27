# Умные и чинимые реплаи — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить дубли чат-сообщений и рвущиеся reply-цепочки, вызванные рассинхроном namespace (marked vs unmarked peer_id) между realtime и поллером.

**Architecture:** Вводим единый `chat_namespace()` helper — один источник правды для составного `post_id` чата, используемый и поллером (`search_chat`), и realtime (`_on_message`). Чиним `_resolve_locally`, чтобы неполная цепочка не помечалась завершённой. Добавляем одноразовый скрипт схлопывания накопившихся дублей и бэкфилла оборванных веток.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, Telethon, pytest.

## Global Constraints

- Ответы пользователю — на русском.
- Бэкенд перезапускает АССИСТЕНТ через `launchctl kickstart -k gui/$(id -u)/com.echo.backend`, НЕ пользователь.
- Сообщения коммитов заканчиваются строкой: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Работаем в текущем каталоге (без worktree). Интерпретатор — `python3`.
- Тесты гоняются `python3 -m pytest` из каталога `backend/`.
- Канальный `post_id` — голый числовой (`str(msg.id)`); чатовый — составной `<namespace>/<msgid>`.
- Ветка: `feat/intel-thread-context`.

---

### Task 1: `chat_namespace()` helper

**Files:**
- Modify: `backend/radar/core/providers/telegram.py` (добавить функцию рядом с `_parse_tg_chat_message`, ~строка 90)
- Test: `backend/tests/test_chat_namespace.py`

**Interfaces:**
- Produces: `chat_namespace(username: str | None, chat_id) -> str` — возвращает canonical namespace чата для составного `post_id`. Есть username → `username.lstrip("@").lower()`. Иначе → unmarked peer_id строкой (через `telethon.utils.resolve_id`). Ввод `chat_id` может быть `int`, `str`, `"#<id>"`, `"-100<id>"`; нечисловой ввод без username возвращается как есть (без падения).

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_chat_namespace.py`:

```python
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
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_chat_namespace.py -v`
Expected: FAIL — `ImportError: cannot import name 'chat_namespace'`.

- [ ] **Step 3: Реализовать helper**

В `backend/radar/core/providers/telegram.py` сразу перед `def _parse_tg_chat_message` добавить:

```python
def chat_namespace(username, chat_id) -> str:
    """Канонический namespace составного post_id чата — единый для поллера и realtime.

    Есть @username → он (без '@', lower). Иначе → unmarked peer_id строкой:
    Telethon отдаёт chat_id супергрупп/каналов в marked-форме ('-100<id>'),
    а резолв invite даёт '#<id>' (unmarked) — приводим оба к unmarked, чтобы одно
    сообщение давало один post_id обоими путями. Нечисловой ввод без username
    возвращаем как есть (не падаем)."""
    if username:
        return str(username).lstrip("@").lower()
    raw = str(chat_id if chat_id is not None else "").strip().lstrip("#")
    try:
        from telethon.utils import resolve_id
        marked = int(raw)
        real_id, _ = resolve_id(marked)
        return str(real_id)
    except (ValueError, TypeError):
        return raw
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd backend && python3 -m pytest tests/test_chat_namespace.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Коммит**

```bash
git add backend/radar/core/providers/telegram.py backend/tests/test_chat_namespace.py
git commit -m "$(cat <<'EOF'
feat(intel): chat_namespace helper для единого post_id чата

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Поллер использует `chat_namespace` в `search_chat`

**Files:**
- Modify: `backend/radar/core/providers/telegram.py` — `search_chat` (~строка 486, последняя строка возврата)
- Test: ручная проверка через Task 3 (регресс-тест паритета). Отдельного теста на `search_chat` нет — он требует живого Telethon-клиента; паритет проверяется в Task 3.

**Interfaces:**
- Consumes: `chat_namespace` из Task 1.
- Produces: `search_chat` теперь намспейсит чатовые `post_id` через `chat_namespace(entity.username, entity.id)` вместо сырого `h`.

- [ ] **Step 1: Изменить namespace в `search_chat`**

В `backend/radar/core/providers/telegram.py` в методе `search_chat` строка:

```python
        return [_parse_tg_chat_message(m, h, h) for m in msgs if getattr(m, "id", None)]
```

заменить на:

```python
        ns = chat_namespace(getattr(entity, "username", None), getattr(entity, "id", None))
        return [_parse_tg_chat_message(m, ns, h) for m in msgs if getattr(m, "id", None)]
```

(Второй аргумент `h` остаётся fallback-автором — он используется только когда у сообщения нет sender-username.)

- [ ] **Step 2: Прогнать существующий набор интел-тестов — убедиться, что ничего не сломалось**

Run: `cd backend && python3 -m pytest tests/test_intel_collector.py tests/test_intel_handle.py -v`
Expected: PASS (все ранее зелёные тесты остаются зелёными).

- [ ] **Step 3: Коммит**

```bash
git add backend/radar/core/providers/telegram.py
git commit -m "$(cat <<'EOF'
fix(intel): поллер намспейсит чат post_id через chat_namespace

search_chat больше не использует сырой handle/#id; namespace берётся
из resolved-entity (username или unmarked peer_id), совпадая с realtime.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Realtime использует `chat_namespace` + регресс-тест паритета

**Files:**
- Modify: `backend/radar/intel/realtime.py` — `_on_message`, ветка `kind == "chat"` (~строка 269)
- Modify: `backend/radar/intel/realtime.py` — импорт `chat_namespace` (верх файла, рядом с импортом парсеров, ~строка 30)
- Test: `backend/tests/test_realtime_namespace.py`

**Interfaces:**
- Consumes: `chat_namespace` из Task 1; `_parse_tg_chat_message` из провайдера.
- Produces: realtime-чат `post_id` совпадает с поллерским для одного и того же сообщения username-less группы.

- [ ] **Step 1: Написать падающий регресс-тест паритета**

Создать `backend/tests/test_realtime_namespace.py`:

```python
"""Регресс: realtime и поллер дают ОДИН post_id для одного сообщения чата без @username.
Иначе (platform, post_id) не дедупит -> дубли + рвётся reply-цепочка."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace


def _msg(mid):
    return SimpleNamespace(
        id=mid, message="по складу прилёт, вторичная детонация",
        date=datetime.now(timezone.utc), sender=None, reply_to_msg_id=None,
        views=0, forwards=0,
    )


def test_realtime_and_poller_agree_on_namespace_username_less():
    from radar.core.providers.telegram import _parse_tg_chat_message, chat_namespace

    marked_chat_id = -1001234567890   # как отдаёт Telethon event.chat_id
    unmarked = "1234567890"           # как хранит probe.query: '#1234567890'

    # Поллер: namespace из resolved-entity (username=None, id=unmarked peer)
    poller_ns = chat_namespace(None, 1234567890)
    poller_post = _parse_tg_chat_message(_msg(567), poller_ns, "#1234567890")

    # Realtime: namespace из marked event.chat_id, username отсутствует
    rt_ns = chat_namespace(None, marked_chat_id)
    rt_post = _parse_tg_chat_message(_msg(567), rt_ns, "@chat")

    assert poller_ns == unmarked
    assert rt_ns == unmarked
    assert rt_post.post_id == poller_post.post_id == "1234567890/567"
```

- [ ] **Step 2: Запустить — убедиться, что тест проходит уже сейчас**

Run: `cd backend && python3 -m pytest tests/test_realtime_namespace.py -v`
Expected: PASS — Task 1+2 уже обеспечивают паритет на уровне провайдера. Этот тест фиксирует контракт. (Если падает — значит регресс в Task 1, чинить там.)

- [ ] **Step 3: Перевести realtime `_on_message` на helper**

В `backend/radar/intel/realtime.py` импорт парсеров (~строка 30):

```python
from ..core.providers.telegram import _parse_tg_message, _parse_tg_chat_message
```

заменить на:

```python
from ..core.providers.telegram import (
    _parse_tg_message, _parse_tg_chat_message, chat_namespace,
)
```

Затем в `_on_message`, ветка чата:

```python
            if kind == "chat":
                ns = username or str(getattr(event, "chat_id", "chat"))
                post = _parse_tg_chat_message(msg, ns, "@" + username if username else "@chat")
```

заменить на:

```python
            if kind == "chat":
                ns = chat_namespace(username, getattr(event, "chat_id", None))
                post = _parse_tg_chat_message(msg, ns, "@" + username if username else "@chat")
```

- [ ] **Step 4: Прогнать realtime/hide-тесты — убедиться, что ничего не сломалось**

Run: `cd backend && python3 -m pytest tests/test_realtime_namespace.py tests/test_intel_hide.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/radar/intel/realtime.py backend/tests/test_realtime_namespace.py
git commit -m "$(cat <<'EOF'
fix(intel): realtime намспейсит чат post_id через chat_namespace

Снимает -100-префикс с event.chat_id -> совпадает с поллерским #id.
Устраняет дубли и рвущиеся reply-цепочки у групп без @username.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Фикс RC-B — неполная цепочка не помечается завершённой

**Files:**
- Modify: `backend/radar/intel/context_pass.py` — `_resolve_locally` (строки 122-126)
- Test: `backend/tests/test_context_pass_partial.py`

**Interfaces:**
- Consumes: `_resolve_locally(session, mention) -> bool` (существующая сигнатура).
- Produces: `_resolve_locally` ставит `thread_root_id` и `context_fetched=True` ТОЛЬКО когда верхний достигнутый узел реально корневой (`reply_to_tg_id` пустой). Если хвост оборван (родителя нет в БД) — возвращает `False`, оставляя `context_fetched=False`, чтобы сетевой `enrich_context` дочинил. `reply_to_id` (прямой родитель) ставится как раньше.

- [ ] **Step 1: Написать падающие тесты**

Создать `backend/tests/test_context_pass_partial.py`:

```python
"""RC-B: неполная локальная цепочка не должна помечаться завершённой —
иначе сетевой догруз её не дочинит и thread_root_id будет неверным."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _m(s, post_id, reply_to=None):
    from radar.intel.models import IntelMention
    m = IntelMention(platform="telegram", post_id=post_id, author="@u", side="ru",
                     text="t", created_at=datetime.now(timezone.utc),
                     reply_to_tg_id=reply_to)
    s.add(m); s.flush()
    return m


def test_complete_chain_marks_done_with_root():
    """Родитель локален и сам корневой -> цепочка полная: done + thread_root_id."""
    from radar.intel import passes  # noqa – регистрирует модели
    from radar.intel.context_pass import _resolve_locally
    s = _sess()
    root = _m(s, "ns/10", reply_to=None)          # настоящий корень (нет родителя)
    reply = _m(s, "ns/11", reply_to="10")          # ответ на корень
    s.commit()

    ok = _resolve_locally(s, reply)
    assert ok is True
    assert reply.reply_to_id == root.id
    assert reply.thread_root_id == root.id
    assert reply.context_fetched is True


def test_partial_chain_not_marked_done():
    """Прямой родитель локален, но ЕГО родителя в БД нет -> хвост оборван.
    Не помечаем завершённой и не ставим thread_root_id — дочинит сеть."""
    from radar.intel import passes  # noqa
    from radar.intel.context_pass import _resolve_locally
    s = _sess()
    parent = _m(s, "ns/20", reply_to="5")          # ссылается на 5, которого нет в БД
    reply = _m(s, "ns/21", reply_to="20")
    s.commit()

    ok = _resolve_locally(s, reply)
    assert ok is False, "оборванная цепочка не считается разрешённой локально"
    assert reply.reply_to_id == parent.id, "прямой родитель всё равно проставлен"
    assert reply.thread_root_id is None, "корень неизвестен — не выдумываем"
    assert reply.context_fetched is False, "сеть должна дочинить хвост"
```

- [ ] **Step 2: Запустить — убедиться, что `test_partial_chain_not_marked_done` падает**

Run: `cd backend && python3 -m pytest tests/test_context_pass_partial.py -v`
Expected: `test_complete_chain_marks_done_with_root` PASS; `test_partial_chain_not_marked_done` FAIL (сейчас ставится `thread_root_id=chain[-1].id` и `context_fetched=True`).

- [ ] **Step 3: Починить `_resolve_locally`**

В `backend/radar/intel/context_pass.py` блок (строки 122-126):

```python
    # The last node whose own parent was NOT found locally is the resolved root.
    mention.thread_root_id = chain[-1].id
    mention.context_fetched = True
    session.commit()
    return True
```

заменить на:

```python
    # Цепочка полна ТОЛЬКО если верхний достигнутый узел реально корневой
    # (у него нет родителя). Если хвост оборван (родитель не в БД) — оставляем
    # context_fetched=False, чтобы сетевой enrich_context дочинил ветку и нашёл
    # настоящий корень. reply_to_id (прямой родитель) уже проставлен выше.
    top = chain[-1]
    if not top.reply_to_tg_id:
        mention.thread_root_id = top.id
        mention.context_fetched = True
        session.commit()
        return True
    session.commit()  # сохраняем reply_to_id + materialised parent-rows
    return False
```

- [ ] **Step 4: Запустить — оба теста проходят**

Run: `cd backend && python3 -m pytest tests/test_context_pass_partial.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Регрессия — realtime локальный резолв всё ещё работает**

Run: `cd backend && python3 -m pytest tests/test_intel_hide.py -v`
Expected: PASS (изменение в `_resolve_locally` не ломает существующий путь; `store_realtime_post` игнорирует возвращаемое значение).

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/context_pass.py backend/tests/test_context_pass_partial.py
git commit -m "$(cat <<'EOF'
fix(intel): не помечать неполную reply-цепочку завершённой

_resolve_locally ставит thread_root_id/context_fetched только когда
верхний локальный узел реально корневой; иначе сеть дочинит хвост.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Скрипт схлопывания дублей + бэкфилла оборванных веток

**Files:**
- Create: `backend/scripts/dedup_chat_namespace.py`
- Test: `backend/tests/test_dedup_chat_namespace.py`

**Interfaces:**
- Consumes: `chat_namespace` (Task 1); модели `IntelMention`, `IntelThreadContext`.
- Produces:
  - `find_namespace_dupes(session) -> list[tuple[IntelMention, IntelMention]]` — пары `(keep, drop)`: одно и то же сообщение чата, сохранённое и в marked (`-100…/m`), и в unmarked (`<id>/m`) namespace. `keep` — запись с непустым thread-контекстом, иначе с меньшим id.
  - `collapse_dupe(session, keep, drop) -> None` — перевесить `IntelThreadContext.mention_id`, чужие `reply_to_id`/`thread_root_id` с `drop` на `keep`, удалить `drop`.
  - `reset_broken_chains(session, limit=200) -> int` — для упоминаний с `reply_to_tg_id IS NOT NULL` и `reply_to_id IS NULL` сбросить `context_fetched=False`; вернуть число затронутых. Возвращает счётчик.
  - `main(argv)` — CLI: `--dry-run` (по умолчанию) печатает план; `--apply` выполняет; `--db <path>` путь к БД (по умолчанию `echo_radar.db`).

- [ ] **Step 1: Написать падающие тесты**

Создать `backend/tests/test_dedup_chat_namespace.py`:

```python
"""Скрипт схлопывания marked/unmarked дублей чат-сообщений и бэкфилла оборванных веток."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from datetime import datetime, timezone


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _m(s, post_id, **kw):
    from radar.intel.models import IntelMention
    m = IntelMention(platform="telegram", post_id=post_id, author="@u", side="ru",
                     text="t", created_at=datetime.now(timezone.utc), **kw)
    s.add(m); s.flush()
    return m


def test_find_pairs_marked_and_unmarked():
    from dedup_chat_namespace import find_namespace_dupes
    s = _sess()
    marked = _m(s, "-1001234567890/567")
    unmarked = _m(s, "1234567890/567")
    _m(s, "1234567890/999")  # одиночка — не пара
    s.commit()

    pairs = find_namespace_dupes(s)
    assert len(pairs) == 1
    keep, drop = pairs[0]
    ids = {keep.post_id, drop.post_id}
    assert ids == {"-1001234567890/567", "1234567890/567"}
    # keep — unmarked (канонический), drop — marked
    assert keep.post_id == "1234567890/567"


def test_collapse_repoints_context_and_refs():
    from dedup_chat_namespace import collapse_dupe
    from radar.intel.models import IntelThreadContext, IntelMention
    s = _sess()
    keep = _m(s, "1234567890/567")
    drop = _m(s, "-1001234567890/567")
    # чужое упоминание ссылается на drop
    child = _m(s, "1234567890/600", reply_to_id=drop.id, thread_root_id=drop.id)
    ctx = IntelThreadContext(mention_id=drop.id, tg_msg_id="500", role="parent",
                             depth=1, author="@a", text="x",
                             created_at=datetime.now(timezone.utc))
    s.add(ctx); s.commit()

    collapse_dupe(s, keep, drop)
    s.commit()

    assert s.get(IntelMention, drop.id) is None
    assert s.query(IntelThreadContext).filter_by(mention_id=keep.id).count() == 1
    refreshed = s.get(IntelMention, child.id)
    assert refreshed.reply_to_id == keep.id
    assert refreshed.thread_root_id == keep.id


def test_reset_broken_chains():
    from dedup_chat_namespace import reset_broken_chains
    s = _sess()
    broken = _m(s, "ns/1", reply_to_tg_id="9", reply_to_id=None, context_fetched=True)
    ok = _m(s, "ns/2", reply_to_tg_id="9", reply_to_id=broken.id, context_fetched=True)
    s.commit()

    n = reset_broken_chains(s, limit=200)
    s.commit()
    assert n == 1
    assert s.get(type(broken), broken.id).context_fetched is False
    assert s.get(type(ok), ok.id).context_fetched is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_dedup_chat_namespace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dedup_chat_namespace'`.

- [ ] **Step 3: Реализовать скрипт**

Создать `backend/scripts/dedup_chat_namespace.py`:

```python
"""Одноразовый ремонт БД после фикса namespace чатов.

1. Схлопывает дубли одного сообщения, сохранённого и в marked ('-100<id>/m'),
   и в unmarked ('<id>/m') namespace (баг до chat_namespace).
2. Бэкфилл: сбрасывает context_fetched у реплаев с оборванной цепочкой, чтобы
   следующий тик enrich_context пере-собрал ветку с правильным namespace.

По умолчанию --dry-run (печатает план). Реальные изменения — только с --apply.
Бэкенд перезапускает ассистент, не пользователь.
"""
from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from radar.models import Base
import radar.intel.models  # noqa – регистрирует модели
from radar.intel.models import IntelMention, IntelThreadContext
from radar.core.providers.telegram import chat_namespace


def _split(post_id: str):
    """('-100123/567') -> ('-100123', '567'); голый id -> (post_id, '')."""
    if "/" not in post_id:
        return post_id, ""
    ns, msgid = post_id.rsplit("/", 1)
    return ns, msgid


def _canonical_ns(ns: str) -> str:
    """unmarked-форма namespace; для '@user'/'user' остаётся как есть."""
    return chat_namespace(None, ns) if ns.lstrip("-").isdigit() else ns


def find_namespace_dupes(session: Session):
    """Пары (keep, drop): одно сообщение чата в двух namespace-формах.

    Группируем по (canonical_ns, msgid). В группе >1 записи keep — с непустым
    thread-контекстом, иначе с меньшим id; остальные — drop."""
    groups: dict[tuple, list[IntelMention]] = {}
    for m in session.query(IntelMention).filter(IntelMention.post_id.like("%/%")).all():
        ns, msgid = _split(m.post_id)
        if not msgid:
            continue
        key = (_canonical_ns(ns), msgid)
        groups.setdefault(key, []).append(m)

    pairs = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # разные post_id внутри группы = реальный namespace-дубль
        if len({m.post_id for m in members}) < 2:
            continue
        ctx_counts = {
            m.id: session.query(IntelThreadContext)
            .filter_by(mention_id=m.id).count()
            for m in members
        }
        keep = max(members, key=lambda m: (ctx_counts[m.id], -m.id))
        for drop in members:
            if drop.id != keep.id:
                pairs.append((keep, drop))
    return pairs


def collapse_dupe(session: Session, keep: IntelMention, drop: IntelMention) -> None:
    """Перевесить контекст и ссылки с drop на keep, удалить drop."""
    (session.query(IntelThreadContext)
        .filter_by(mention_id=drop.id)
        .update({IntelThreadContext.mention_id: keep.id}, synchronize_session=False))
    (session.query(IntelMention)
        .filter_by(reply_to_id=drop.id)
        .update({IntelMention.reply_to_id: keep.id}, synchronize_session=False))
    (session.query(IntelMention)
        .filter_by(thread_root_id=drop.id)
        .update({IntelMention.thread_root_id: keep.id}, synchronize_session=False))
    session.delete(drop)


def reset_broken_chains(session: Session, limit: int = 200) -> int:
    """Сбросить context_fetched у реплаев с оборванной цепочкой (нет reply_to_id),
    чтобы enrich_context пере-собрал ветку. Возвращает число затронутых."""
    rows = (session.query(IntelMention)
            .filter(IntelMention.reply_to_tg_id.isnot(None),
                    IntelMention.reply_to_id.is_(None),
                    IntelMention.context_fetched.is_(True))
            .limit(limit).all())
    for m in rows:
        m.context_fetched = False
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ремонт namespace-дублей и оборванных reply-цепочек")
    ap.add_argument("--db", default="echo_radar.db", help="путь к SQLite БД")
    ap.add_argument("--apply", action="store_true", help="выполнить (иначе dry-run)")
    ap.add_argument("--backfill-limit", type=int, default=200)
    args = ap.parse_args(argv)

    eng = create_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(eng)
    session = Session(eng)
    try:
        pairs = find_namespace_dupes(session)
        print(f"namespace-дублей найдено: {len(pairs)}")
        for keep, drop in pairs:
            print(f"  keep={keep.post_id}(id={keep.id})  drop={drop.post_id}(id={drop.id})")

        if args.apply:
            for keep, drop in pairs:
                collapse_dupe(session, keep, drop)
            n = reset_broken_chains(session, args.backfill_limit)
            session.commit()
            print(f"схлопнуто пар: {len(pairs)}; сброшено оборванных цепочек: {n}")
        else:
            n = (session.query(IntelMention)
                 .filter(IntelMention.reply_to_tg_id.isnot(None),
                         IntelMention.reply_to_id.is_(None),
                         IntelMention.context_fetched.is_(True))
                 .limit(args.backfill_limit).count())
            print(f"[dry-run] к бэкфиллу оборванных цепочек: {n}. Запусти с --apply.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python3 -m pytest tests/test_dedup_chat_namespace.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Сухой прогон на боевой БД (только чтение)**

Run: `cd backend && python3 scripts/dedup_chat_namespace.py --dry-run`
Expected: печатает список найденных пар и число к бэкфиллу; БД не меняется.

- [ ] **Step 6: Коммит**

```bash
git add backend/scripts/dedup_chat_namespace.py backend/tests/test_dedup_chat_namespace.py
git commit -m "$(cat <<'EOF'
feat(intel): скрипт схлопывания namespace-дублей + бэкфилл цепочек

dedup_chat_namespace.py: схлопывает marked/unmarked дубли одного
сообщения и сбрасывает context_fetched у оборванных reply-веток.
--dry-run по умолчанию, изменения только с --apply.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Применить ремонт к боевой БД и перезапустить бэкенд

**Files:** нет изменений кода — операционный шаг.

**Interfaces:**
- Consumes: скрипт из Task 5; все фиксы из Task 1-4 уже в коде.

- [ ] **Step 1: Полный прогон тестов интел-домена**

Run: `cd backend && python3 -m pytest tests/test_chat_namespace.py tests/test_realtime_namespace.py tests/test_context_pass_partial.py tests/test_dedup_chat_namespace.py tests/test_intel_collector.py tests/test_intel_handle.py tests/test_intel_hide.py tests/test_intel_keyword_filter.py -v`
Expected: PASS (все).

- [ ] **Step 2: Бэкап боевой БД**

Run: `cd backend && cp echo_radar.db echo_radar.db.bak-$(date +%Y%m%d-%H%M%S)`
Expected: создан файл бэкапа.

- [ ] **Step 3: Применить ремонт**

Run: `cd backend && python3 scripts/dedup_chat_namespace.py --apply`
Expected: печатает «схлопнуто пар: N; сброшено оборванных цепочек: M».

- [ ] **Step 4: Перезапустить бэкенд (выполняет АССИСТЕНТ)**

Run: `launchctl kickstart -k gui/$(id -u)/com.echo.backend`
Expected: бэкенд перезапущен с новым кодом namespace; следующий тик `enrich_context` дочинит сброшенные цепочки.

- [ ] **Step 5: Проверить, что новых дублей не появляется**

Run: `cd backend && python3 scripts/dedup_chat_namespace.py --dry-run`
Expected: «namespace-дублей найдено: 0» (после ремонта и с исправленным кодом новые не копятся).

---

## Self-Review

**Spec coverage:**
- §1 единый namespace-helper → Task 1 (helper) + Task 2 (поллер) + Task 3 (realtime). ✓
- §2 фикс RC-B → Task 4. ✓
- §3 скрипт схлопывания дублей → Task 5 (`find_namespace_dupes`/`collapse_dupe`) + Task 6 (применение). ✓
- §4 бэкфилл оборванных цепочек → Task 5 (`reset_broken_chains`) + Task 6. ✓
- §5 тесты → каждая задача содержит тесты; Task 6 Step 1 — сводный прогон. ✓
- За рамками (LLM-классификация, схема БД, сиблинги) — в план не включено, соответствует спеке. ✓

**Placeholder scan:** плейсхолдеров нет — весь код приведён целиком.

**Type consistency:** `chat_namespace(username, chat_id) -> str` используется одинаково в Task 1/2/3. `_resolve_locally(session, mention) -> bool` сохраняет сигнатуру. Функции скрипта (`find_namespace_dupes`, `collapse_dupe`, `reset_broken_chains`, `main`) согласованы между тестами и реализацией.
