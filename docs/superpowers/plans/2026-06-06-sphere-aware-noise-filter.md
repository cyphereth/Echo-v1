# Sphere-aware Noise Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make noise detection depend on the brand's sphere — a slim universal cheap layer plus a sphere-aware AI judge — and ensure the brand name is always searched, so a non-marketplace brand (e.g. Тануки, a sushi chain) gets a relevant, non-empty feed.

**Architecture:** Layer 1 (`looks_like_ad_cheap`, collect-time, free) keeps only sphere-independent junk rules. Layer 2 (`classify_ads_batch`, pipeline, batched Haiku) takes the brand's `sphere` and decides noise-vs-relevant per sphere. A separate small fix guarantees the brand name lands in `keywords`.

**Tech Stack:** Python / FastAPI / SQLAlchemy / SQLite, Anthropic Messages API (Haiku), pytest. Binary is `python3`. Run backend: `cd backend && uvicorn radar.api:app --host 127.0.0.1 --port 8000` (log `/tmp/echo_backend.log`). Demo login `demo@echo.app` / `demo12345`.

---

## File Structure

- `backend/radar/spam.py` — slim `looks_like_ad_cheap`; add `_build_ads_classify_payload`; make `classify_ads_batch` sphere-aware.
- `backend/radar/pipeline.py:55` — pass `brand.sphere` into `classify_ads_batch`.
- `backend/radar/api.py` — add `_ensure_name_in_keywords` helper; apply at `/onboarding` and `/brands/{id}/config`; tweak `_profile_with_claude` prompt.
- `backend/tests/test_profile_scan.py` — update affected spam tests, add new ones.

---

### Task 1: Slim the cheap layer to universal junk only

**Files:**
- Modify: `backend/radar/spam.py` — `looks_like_ad_cheap` (~line 110-128) and remove now-unused constants `SALES_PHRASES`, `MAX_LEN`, `MAX_HASHTAGS`, `_HASHTAG_RE`.
- Test: `backend/tests/test_profile_scan.py` — replace 4 existing spam tests, keep 3.

- [ ] **Step 1: Rewrite the affected tests (they encode the OLD behavior)**

In `backend/tests/test_profile_scan.py`, the spam test block currently has these. **Keep** `test_spam_seller_username`, `test_spam_too_short`, `test_spam_real_post_passes` unchanged. **Replace** `test_spam_sales_phrase`, `test_spam_too_long`, `test_spam_hashtag_stuffing`, `test_spam_inline_hashtag_stuffing` with the new tests below (delete the four old functions by name, add these):

```python
def test_cheap_ignores_marketplace_phrase():
    # "промокод"/"артикул" are sphere-specific noise now judged by the AI, not the cheap layer
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("заказал по промокоду в тануки, ролл огонь", "katya_msk", []) is False

def test_cheap_allows_long_caption():
    from radar.spam import looks_like_ad_cheap
    long_caption = "Сегодня заехали в новый ресторан японской кухни, " * 5  # ~250 chars, normal
    assert looks_like_ad_cheap(long_caption, "foodie_anna", []) is False

def test_cheap_allows_many_hashtags():
    # food/lifestyle posts routinely use >3 hashtags — not junk by itself
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap(
        "обалденные роллы в тануки сегодня", "user_masha",
        ["суши", "роллы", "японскаякухня", "вкусно", "доставка", "ужин"]) is False

def test_cheap_allows_inline_hashtags():
    from radar.spam import looks_like_ad_cheap
    assert looks_like_ad_cheap("крутая подборка роллов #суши#роллы#еда#доставка#ужин", "user1", []) is False
```

- [ ] **Step 2: Run to verify the new tests FAIL and old behavior is gone**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "cheap_ or spam_" -v`
Expected: the 4 new `test_cheap_*` FAIL (current code still flags them True via SALES_PHRASES / MAX_LEN / MAX_HASHTAGS).

- [ ] **Step 3: Slim `looks_like_ad_cheap` and remove dead constants**

In `backend/radar/spam.py`, replace the whole `looks_like_ad_cheap` function (currently starting `def looks_like_ad_cheap(text: str, author: str, hashtags: Optional[list] = None,`) with:

```python
def looks_like_ad_cheap(text: str, author: str, hashtags: Optional[list] = None,
                        min_len: int = MIN_LEN) -> bool:
    """Level-1 UNIVERSAL junk — no network, sphere-independent. True only for junk in
    EVERY sphere: too-short text, or a dropshipper/seller handle. Sphere-specific noise
    (marketplace sales phrases, heavy hashtags, long promos) is left to the sphere-aware
    AI judge in classify_ads_batch."""
    raw = text or ""
    if len(raw) < min_len:
        return True
    a = (author or "").lower()
    if any(h in a for h in SELLER_NAME_HINTS):
        return True
    return False
```

Then delete the now-unused module constants and regex: remove the `_HASHTAG_RE = ...` line, the `MAX_LEN = 150` line, the `MAX_HASHTAGS = 3` line, and the entire `SALES_PHRASES = [ ... ]` list. Keep `MIN_LEN = 20`, `SELLER_NAME_HINTS`, `import re` (still used by `looks_like_provider_cheap`), and everything else.

- [ ] **Step 4: Run the full file to verify pass + no regressions**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -q`
Expected: all pass (the 4 new `test_cheap_*`, the 3 kept spam tests, and everything else).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/spam.py backend/tests/test_profile_scan.py
git commit -m "feat: slim cheap spam layer to universal junk (sphere-specific noise → AI judge)"
```

---

### Task 2: Sphere-aware AI judge

**Files:**
- Modify: `backend/radar/spam.py` — add `_build_ads_classify_payload`; make `classify_ads_batch(texts, sphere="")` use it.
- Modify: `backend/radar/pipeline.py:55` — pass `brand.sphere`.
- Test: `backend/tests/test_profile_scan.py`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_profile_scan.py`:

```python
# ── sphere-aware ad classifier payload ────────────────────────────────────────

def test_build_ads_payload_includes_sphere():
    from radar.spam import _build_ads_classify_payload
    p = _build_ads_classify_payload(["текст про роллы"], sphere="сеть японских ресторанов")
    assert "сеть японских ресторанов" in p["system"]

def test_build_ads_payload_includes_texts():
    from radar.spam import _build_ads_classify_payload
    p = _build_ads_classify_payload(["уникальный_маркер_текста"], sphere="")
    assert "уникальный_маркер_текста" in p["messages"][0]["content"]

def test_build_ads_payload_no_sphere_ok():
    from radar.spam import _build_ads_classify_payload
    p = _build_ads_classify_payload(["a", "b"], sphere="")
    assert p["model"] == "claude-haiku-4-5-20251001"
    assert isinstance(p["max_tokens"], int) and p["max_tokens"] > 0
```

(The existing `test_classify_ads_batch_no_key` must keep passing unchanged — `classify_ads_batch(["a","b","c"])` still works because `sphere` has a default.)

- [ ] **Step 2: Run to verify FAIL**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "ads_payload" -v`
Expected: FAIL — ImportError: cannot import name `_build_ads_classify_payload`.

- [ ] **Step 3: Add the payload builder and rewire `classify_ads_batch`**

In `backend/radar/spam.py`, add this function directly above the existing `def classify_ads_batch(`:

```python
def _build_ads_classify_payload(texts: list, sphere: str = "") -> dict:
    """Anthropic request for the sphere-aware noise judge. Marks NOISE (foreign
    ads/sellers, off-topic) vs RELEVANT mentions, judged for the brand's sphere."""
    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    ctx = f'Бренд работает в сфере: "{sphere}". ' if sphere else ""
    system = (
        "Ты фильтр релевантности для мониторинга бренда. " + ctx +
        "Для каждого текста реши: это ШУМ (чужая реклама, продавец-дропшиппер, "
        "оффтоп, не относится к сфере бренда) — или РЕЛЕВАНТНЫЙ пост/упоминание "
        "(мнение, опыт, вопрос, обсуждение по теме бренда). Отвечай ТОЛЬКО валидным JSON."
    )
    user = (
        f"Тексты:\n{numbered}\n\n"
        f'Верни JSON-массив по одному объекту на текст: '
        f'[{{"i":0,"is_ad":false}}, ...]. is_ad=true только для шума.'
    )
    return {"model": "claude-haiku-4-5-20251001", "max_tokens": 40 + len(texts) * 20,
            "system": system, "messages": [{"role": "user", "content": user}]}
```

Then change `classify_ads_batch` to take `sphere` and use the builder. Replace its signature line `def classify_ads_batch(texts: list) -> list:` with:

```python
def classify_ads_batch(texts: list, sphere: str = "") -> list:
```

and inside it, replace the inline `numbered = ...`, `system = (...)`, `user = (...)` block AND the `json={...}` argument in `_call` so that `_call` posts `json=_build_ads_classify_payload(texts, sphere)`. Concretely, the `_call` body becomes:

```python
    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=_build_ads_classify_payload(texts, sphere),
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)
```

Delete the now-unused `numbered`/`system`/`user` locals that preceded `_call` in `classify_ads_batch`. Keep the `n = len(texts)`, the `if n == 0`/`if not LLM_API_KEY` guards, `import httpx`, and the result-parsing block after `_call` unchanged.

- [ ] **Step 4: Pass the brand sphere from the pipeline**

In `backend/radar/pipeline.py`, line 55 currently:

```python
        flags = classify_ads_batch([m.text for m in unclassified])
```

Replace with:

```python
        flags = classify_ads_batch([m.text for m in unclassified], sphere=getattr(brand, "sphere", "") or "")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -q`
Expected: all pass (new `ads_payload` tests + existing `test_classify_ads_batch_no_key`).

- [ ] **Step 6: Commit**

```bash
git add backend/radar/spam.py backend/radar/pipeline.py backend/tests/test_profile_scan.py
git commit -m "feat: sphere-aware ad/noise classifier — judge relevance per brand sphere"
```

---

### Task 3: Guarantee the brand name is searched

**Files:**
- Modify: `backend/radar/api.py` — add `_ensure_name_in_keywords` (near `_clean_list`, ~line 164); apply at `/onboarding` (~line 653) and `/brands/{id}/config` (~line 392); add a keywords instruction to `_profile_with_claude` prompt (~line 215).
- Test: `backend/tests/test_profile_scan.py`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_profile_scan.py`:

```python
# ── brand-name guaranteed in keywords ─────────────────────────────────────────

def test_ensure_name_prepends_when_missing():
    from radar.api import _ensure_name_in_keywords
    assert _ensure_name_in_keywords("Тануки", ["суши", "роллы"]) == ["Тануки", "суши", "роллы"]

def test_ensure_name_noop_when_present_substring_ci():
    from radar.api import _ensure_name_in_keywords
    # already covered (case-insensitive substring) → unchanged
    assert _ensure_name_in_keywords("Самокат", ["самокат доставка", "еда"]) == ["самокат доставка", "еда"]

def test_ensure_name_empty_name_noop():
    from radar.api import _ensure_name_in_keywords
    assert _ensure_name_in_keywords("", ["суши"]) == ["суши"]
    assert _ensure_name_in_keywords("   ", ["суши"]) == ["суши"]
```

- [ ] **Step 2: Run to verify FAIL**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "ensure_name" -v`
Expected: FAIL — ImportError: cannot import name `_ensure_name_in_keywords`.

- [ ] **Step 3: Add the helper**

In `backend/radar/api.py`, add directly below the `_clean_list` function (after its `return out`):

```python
def _ensure_name_in_keywords(name: str, keywords: list[str]) -> list[str]:
    """The brand lane is useless without the brand name. If no keyword already
    contains the brand name (case-insensitive), prepend it."""
    nm = (name or "").strip()
    if not nm:
        return keywords
    low = nm.lower()
    if any(low in (k or "").lower() for k in keywords):
        return keywords
    return [nm] + list(keywords)
```

- [ ] **Step 4: Apply at the two save points**

In `backend/radar/api.py` `/onboarding` (the `Brand(` constructor), change the `keywords=` line from:

```python
        keywords=json.dumps(_clean_list(body.keywords)),
```
to:
```python
        keywords=json.dumps(_ensure_name_in_keywords(body.name, _clean_list(body.keywords))),
```

In `update_brand_config` (`/brands/{brand_id}/config`), change the keywords line from:

```python
    if body.keywords       is not None: b.keywords       = json.dumps(_clean_list(body.keywords))
```
to:
```python
    if body.keywords       is not None: b.keywords       = json.dumps(_ensure_name_in_keywords(body.name or b.name, _clean_list(body.keywords)))
```

- [ ] **Step 5: Tweak the profiler prompt so the AI fills keywords with the name**

In `backend/radar/api.py` `_profile_with_claude`, the `user_msg` currently begins its instructions with the `sphere` line. Insert a keywords instruction immediately before the line `'Определи ДНК бренда — сферу и интересы аудитории 1-2 фразами (поле "sphere"). '`. Add this string literal as a new line in the same parenthesized concatenation:

```python
        'keywords — варианты НАЗВАНИЯ бренда (рус + латиница, включая хэндл и частые '
        'написания), а НЕ нишевые слова. niche_keywords — это про тематику.\n'
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/radar/api.py backend/tests/test_profile_scan.py
git commit -m "fix: always search the brand name (keywords safety net + profiler prompt)"
```

---

### Task 4: Retrofit the Тануки brand and verify end-to-end (operational)

Not TDD — verifies the whole change against real data. Brand id=10 (`tanuki.official`, owner user 16) currently has generic-food keywords and no brand name.

- [ ] **Step 1: Restart backend so it runs the new code**

```bash
cd backend && pkill -f "uvicorn radar.api:app"; sleep 1
(uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &)
sleep 4
```
Use a python3/urllib request to `http://127.0.0.1:8000/health` to confirm 200 (a PreToolUse hook intercepts `curl`).

- [ ] **Step 2: Set name-variant keywords + clear geo + rebuild probes (one python3 script)**

Run from the repo root with `cd backend && python3 - <<'PY'` (so `radar` imports resolve). This sets real keywords, clears the stray `geo='Москва'` (Тануки is a federal chain — geo over-constrained the niche lane), and rebuilds probes via the real `_rebuild_probes`:

```python
import json
from radar.db import get_session
from radar.models import Brand
from radar.api import _rebuild_probes
s = get_session()
b = s.get(Brand, 10)
b.keywords = json.dumps(["Тануки", "tanuki", "тануки доставка", "тануки роллы",
                         "тануки суши", "ресторан тануки"])
b.geo = ""
s.flush()
_rebuild_probes(s, b)
s.commit()
print("probes rebuilt for brand 10")
```

- [ ] **Step 3: Re-collect and run the pipeline (one python3 script)**

`_run_collect(10)` runs the collect + classify pipeline synchronously. Run with `cd backend && python3 - <<'PY'`:

```python
from radar.api import _run_collect
print(_run_collect(10))
```
This is a network + LLM call (TikHub + the sphere-aware Haiku judge); it may take a minute. Watch `/tmp/echo_backend.log` for rate-limit warnings.

- [ ] **Step 4: Verify the feed now has relevant, visible mentions**

```python
import sqlite3
db = sqlite3.connect("backend/echo_radar.db")
total = db.execute("SELECT COUNT(*) FROM mentions WHERE brand_id=10").fetchone()[0]
visible = db.execute("SELECT COUNT(*) FROM mentions WHERE brand_id=10 AND is_spam=0").fetchone()[0]
tanuki = db.execute("SELECT COUNT(*) FROM mentions WHERE brand_id=10 AND is_spam=0 AND (lower(text) LIKE '%тануки%' OR lower(text) LIKE '%tanuki%')").fetchone()[0]
print("total", total, "visible", visible, "mention_tanuki", tanuki)
```
Expected: `visible` > 0 and a meaningful share of visible mentions actually reference Тануки. If `visible` is still ~0, do NOT patch blindly — return to systematic-debugging (re-check which layer hides them).

- [ ] **Step 5: No commit** — this task changes DB data, not source.

---

## Notes
- `LLM_API_KEY` / `TIKHUB_TOKEN` present in `backend/.env`.
- A `curl`/`wget` PreToolUse hook redirects to context-mode — make HTTP calls from `python3` (urllib/httpx) instead.
- The cheap-layer slimming means the AI judge sees more posts (more batched Haiku calls in the background pipeline) — accepted trade-off.
