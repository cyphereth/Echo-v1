# Web-search Keyword Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/brands/suggest` use Anthropic's web_search tool to generate large,
relevance-validated keyword/niche/competitor/audience lists, then enrich the existing
Ozon and CafeBlanche brands with the same approach.

**Architecture:** Split the existing monolithic `suggest_brand` endpoint into two pure,
unit-testable helpers — `_build_suggest_payload(name)` (request body, incl. the
web_search tool + expanded prompt) and `_extract_suggest_json(blocks)` (pull final JSON
out of multi-block tool responses) — then wire them into the endpoint. Part B is an
operational runbook using web research + the existing config endpoint.

**Tech Stack:** Python / FastAPI / SQLAlchemy / SQLite, Anthropic Messages API
(`web_search_20250305` server tool), pytest.

---

## File Structure

- `backend/radar/api.py` — add `_build_suggest_payload` and `_extract_suggest_json`
  helpers; rewrite `suggest_brand` (~line 405) to use them.
- `backend/tests/test_profile_scan.py` — add unit tests for both helpers (existing
  single test file; follow its import-inside-test style).
- No new files. No frontend changes (TagGroup renders any list length).

---

### Task 1: `_extract_suggest_json` helper — parse final JSON from tool-call response

When the web_search tool is attached, Claude's `content` array contains
`server_tool_use` and `web_search_tool_result` blocks interleaved with `text` blocks;
the final JSON answer is in the **last** text block, not the first.

**Files:**
- Modify: `backend/radar/api.py` (add helper near the other `_`-prefixed helpers, e.g.
  just above `suggest_brand` at ~line 400)
- Test: `backend/tests/test_profile_scan.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_profile_scan.py`:

```python
# ── suggest_brand: response parsing ───────────────────────────────────────────

def test_extract_suggest_json_single_text_block():
    from radar.api import _extract_suggest_json
    blocks = [{"type": "text", "text": '{"keywords": ["ozon"]}'}]
    assert _extract_suggest_json(blocks) == {"keywords": ["ozon"]}

def test_extract_suggest_json_takes_last_text_block():
    from radar.api import _extract_suggest_json
    blocks = [
        {"type": "text", "text": "Let me search for this brand."},
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "ozon"}},
        {"type": "web_search_tool_result", "content": [{"title": "Ozon"}]},
        {"type": "text", "text": '{"keywords": ["ozon", "озон"], "competitors": ["wildberries"]}'},
    ]
    assert _extract_suggest_json(blocks) == {
        "keywords": ["ozon", "озон"], "competitors": ["wildberries"]}

def test_extract_suggest_json_strips_markdown_fence():
    from radar.api import _extract_suggest_json
    blocks = [{"type": "text", "text": '```json\n{"keywords": ["x"]}\n```'}]
    assert _extract_suggest_json(blocks) == {"keywords": ["x"]}

def test_extract_suggest_json_no_text_raises():
    import pytest
    from radar.api import _extract_suggest_json
    with pytest.raises(ValueError):
        _extract_suggest_json([{"type": "web_search_tool_result", "content": []}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_profile_scan.py -k extract_suggest -v`
Expected: FAIL — `ImportError: cannot import name '_extract_suggest_json'`

- [ ] **Step 3: Implement the helper**

Add to `backend/radar/api.py` just above `class SuggestBody` (~line 400):

```python
def _extract_suggest_json(blocks: list) -> dict:
    """Pull the brand-suggest JSON out of Claude's response content blocks.
    With the web_search tool the model emits server_tool_use / web_search_tool_result
    blocks and writes its final JSON in the LAST text block."""
    texts = [b["text"] for b in blocks if b.get("type") == "text" and b.get("text")]
    if not texts:
        raise ValueError("no text block in suggest response")
    text = texts[-1].strip()
    text = text.lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_profile_scan.py -k extract_suggest -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/api.py backend/tests/test_profile_scan.py
git commit -m "feat: _extract_suggest_json — parse final JSON from web_search tool response"
```

---

### Task 2: `_build_suggest_payload` helper — request body with web_search + expanded prompt

**Files:**
- Modify: `backend/radar/api.py` (add helper just below `_extract_suggest_json`)
- Test: `backend/tests/test_profile_scan.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_profile_scan.py`:

```python
# ── suggest_brand: request payload ────────────────────────────────────────────

def test_build_suggest_payload_has_web_search_tool():
    from radar.api import _build_suggest_payload
    p = _build_suggest_payload("Ozon")
    tools = p["tools"]
    assert any(t.get("type") == "web_search_20250305" for t in tools)

def test_build_suggest_payload_large_token_budget():
    from radar.api import _build_suggest_payload
    p = _build_suggest_payload("Ozon")
    assert p["max_tokens"] >= 4000

def test_build_suggest_payload_includes_brand_name():
    from radar.api import _build_suggest_payload
    p = _build_suggest_payload("CafeBlanche")
    user_msg = p["messages"][0]["content"]
    assert "CafeBlanche" in user_msg

def test_build_suggest_payload_asks_for_many_keywords():
    from radar.api import _build_suggest_payload
    p = _build_suggest_payload("Ozon")
    user_msg = p["messages"][0]["content"]
    # prompt must request large volumes, not the old 5-7
    assert "20-30" in user_msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_profile_scan.py -k build_suggest -v`
Expected: FAIL — `ImportError: cannot import name '_build_suggest_payload'`

- [ ] **Step 3: Implement the helper**

Add to `backend/radar/api.py` directly below `_extract_suggest_json`:

```python
def _build_suggest_payload(name: str) -> dict:
    """Anthropic Messages request for brand suggestion: web_search tool + a prompt
    that asks for large, relevance-validated term lists."""
    system = (
        "Ты эксперт по SMM и мониторингу брендов в русскоязычных соцсетях "
        "(TikTok, Instagram). Сначала ИЩИ информацию о бренде в интернете "
        "(чем занимается, реальные конкуренты, как о нём пишут), затем дай ответ. "
        "Финальный ответ — ТОЛЬКО валидный JSON без пояснений и markdown-блоков."
    )
    user_msg = (
        f'Изучи бренд "{name}" через веб-поиск и его сферу деятельности, затем '
        f'подбери для мониторинга в TikTok и Instagram МАКСИМАЛЬНО ШИРОКО: '
        f'keywords — 20-30 (вариации названия рус/лат, продукты, фирменные термины); '
        f'niche_keywords — 15-25 (тематика индустрии + смежные интересы ЦА); '
        f'competitors — 10-15 ТОЛЬКО реально существующих компаний, '
        f'подтверждённых веб-поиском (никаких выдуманных); '
        f'audience_terms — 15-20 широких тем целевой аудитории. '
        f'Определи ДНК бренда — сферу и интересы аудитории 1-2 фразами (поле "sphere"). '
        f'Определи город (geo), если это локальный бизнес (салон/клиника в конкретном '
        f'городе) — иначе "". Если это локальный СЕРВИСНЫЙ бизнес — сгенерируй '
        f'category_terms (4-6 категорий ниши города); для федеральных/онлайн брендов '
        f'category_terms=[]. '
        f'Определи рынок: если бренд русскоязычный или ориентирован на СНГ — '
        f'верни "market":"ru" и предлагай ТОЛЬКО русскоязычных конкурентов из СНГ; '
        f'иначе "market":"global". '
        f'РАНЖИРУЙ все термины по релевантности и ОТСЕКАЙ явно нерелевантное '
        f'(омонимы, мусор, не относящееся к бренду). '
        f'Ответ строго в JSON: {{"keywords":[],"hashtags":[],"competitors":[],'
        f'"niche_keywords":[],"sphere":"","geo":"","category_terms":[],'
        f'"audience_terms":[],"market":""}}'
    )
    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_profile_scan.py -k build_suggest -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/api.py backend/tests/test_profile_scan.py
git commit -m "feat: _build_suggest_payload — web_search tool + expanded suggest prompt"
```

---

### Task 3: Wire helpers into `suggest_brand` endpoint

Replace the inline `system`/`user_msg`/`_call` body of `suggest_brand` with the two
helpers. Keep the existing single-retry-on-parse-failure behaviour and the 503/502
error mapping. Note `hashtags` stays in the returned dict (prompt still includes the
key, model may fill it).

**Files:**
- Modify: `backend/radar/api.py` — `suggest_brand` (~line 405-476)

- [ ] **Step 1: Replace the endpoint body**

In `backend/radar/api.py`, replace everything from `system = (` through the end of the
`_call` definition and the `try/except` (the current lines that build `system`,
`user_msg`, define `_call`, and call it) with:

```python
    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=_build_suggest_payload(body.name),
            timeout=120,
        )
        resp.raise_for_status()
        return _extract_suggest_json(resp.json().get("content", []))

    try:
        data = _call()
    except (json.JSONDecodeError, KeyError, ValueError):
        try:
            data = _call()
        except Exception as e:
            log.warning("suggest_brand retry failed: %s", e)
            raise HTTPException(502, "AI suggestion failed")
    except Exception as e:
        log.warning("suggest_brand failed: %s", e)
        raise HTTPException(502, "AI suggestion failed")
```

The `if not LLM_API_KEY: raise HTTPException(503, ...)` guard at the top of the function
and the `return {...}` block at the bottom (mapping data keys) stay unchanged. The
`from .drafts import LLM_API_KEY, LLM_API_URL` and `import httpx` lines stay.

- [ ] **Step 2: Verify existing unit tests still pass**

Run: `cd backend && python -m pytest tests/test_profile_scan.py -v`
Expected: PASS (all tests, including the 8 new helper tests)

- [ ] **Step 3: Live smoke test against the real API**

Ensure backend is running (`cd backend && uvicorn radar.api:app --host 127.0.0.1 --port 8000`, log at `/tmp/echo_backend.log`), then log in and call suggest:

```bash
TOKEN=$(curl -s -X POST 127.0.0.1:8000/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"demo@echo.app","password":"demo12345"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -X POST 127.0.0.1:8000/brands/suggest \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"Ozon"}' | python3 -m json.tool
```

Expected: JSON with `keywords` length ~20+, `competitors` length ~10+ containing real
names (e.g. Wildberries, Яндекс Маркет), `market` == "ru". If it 502s, check
`/tmp/echo_backend.log` — most likely the model wrapped JSON in prose; the retry should
handle transient cases. Confirm the auth field name (`token`) matches the login
response; adjust the extractor if the key differs.

- [ ] **Step 4: Commit**

```bash
git add backend/radar/api.py
git commit -m "feat: suggest_brand uses web_search + expanded prompt for wider coverage"
```

---

### Task 4: Enrich existing brands (Ozon, CafeBlanche) — operational runbook

One-off data enrichment. Not TDD; this writes real term lists to the live DB.

**Files:** none modified (uses running API).

- [ ] **Step 1: Identify the brand IDs**

```bash
curl -s 127.0.0.1:8000/brands -H "authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json;[print(b["id"], b["name"]) for b in json.load(sys.stdin)]'
```

Note the IDs for Ozon and CafeBlanche.

- [ ] **Step 2: Generate expanded terms via the new endpoint**

For each brand, call `/brands/suggest` (as in Task 3 Step 3) with the brand's name and
capture the JSON. Review the lists: drop any term that is clearly irrelevant before
writing. (The implementing agent may instead use its own WebSearch tool to research
Ozon and CafeBlanche and hand-assemble lists — either source is acceptable; the goal is
large, relevant lists.)

- [ ] **Step 3: Write the terms to each brand**

POST the reviewed lists to the config endpoint (this triggers `_rebuild_probes`):

```bash
curl -s -X POST 127.0.0.1:8000/brands/<ID>/config \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"keywords":[...],"niche_keywords":[...],"competitors":[...],"audience_terms":[...]}'
```

Do NOT overwrite `geo`, `local_mode`, or `exclusions` unless intentionally changing
them — omit those fields so they keep their current values.

- [ ] **Step 4: Verify probes rebuilt**

```bash
curl -s 127.0.0.1:8000/brands/<ID> -H "authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json;b=json.load(sys.stdin);print("kw",len(b["keywords"]),"niche",len(b["niche_keywords"]),"comp",len(b["competitors"]))'
```

Expected: counts reflect the expanded lists.

- [ ] **Step 5: Run a collect pass and confirm the feed grows**

Trigger collection via the existing endpoint (runs `_run_collect` as a background task):

```bash
curl -s -X POST 127.0.0.1:8000/brands/<ID>/collect \
  -H "authorization: Bearer $TOKEN"
```

Wait for it to finish (watch `/tmp/echo_backend.log`), then re-check the brand's feed /
mention count and confirm it rose versus before. Watch the log for TikHub rate-limit
warnings — per the spec, collection has no per-probe page cap, so more terms means a
heavier run.

- [ ] **Step 6: No commit**

This task changes DB data, not source. Nothing to commit.

---

## Notes

- `LLM_API_KEY` and `TIKHUB_TOKEN` are present in `backend/.env`.
- Demo login: `demo@echo.app` / `demo12345`.
- web_search billing is per-search + tokens (accepted).
- The frontend `AIWizard.jsx` consumes the same response keys and renders via
  `TagGroup` (`list.map`) with no caps — no frontend change needed.
