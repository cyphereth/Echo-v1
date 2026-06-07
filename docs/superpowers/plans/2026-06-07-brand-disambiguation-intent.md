# Brand Disambiguation + Intent Reach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop off-topic homonyms (e.g. a game `#tanuki`) showing as brand mentions while keeping real ones, and widen niche reach with sphere-appropriate intent phrases that surface as engagement opportunities.

**Architecture:** Replace the brand-lane "skip the judge" bypass with a default-keep AI disambiguation pass (`disambiguate_brand_batch`) that hides only confident off-topic homonyms; niche/competitor keep the existing sphere noise judge. Add intent-phrase generation to the suggest prompts and a cheap intent detector that upgrades the niche opportunity hint.

**Tech Stack:** Python / FastAPI / SQLAlchemy / SQLite, Anthropic Messages API (Haiku), pytest. Binary is `python3`. Run backend: `cd backend && uvicorn radar.api:app --host 127.0.0.1 --port 8000`.

---

## File Structure

- `backend/radar/spam.py` — add `_build_disambiguate_payload` + `disambiguate_brand_batch`.
- `backend/radar/pipeline.py` — brand lane → disambiguation, niche/competitor → noise judge; add `_looks_like_intent`; upgrade `opportunity_for`.
- `backend/radar/api.py` — add intent-phrase guidance to the niche part of `_build_suggest_payload` and `_profile_with_claude`.
- `backend/tests/test_profile_scan.py` — new tests; replace the now-obsolete `test_brand_lane_bypasses_noise_judge`.

---

### Task 1: Brand-lane disambiguation judge (spam.py)

**Files:**
- Modify: `backend/radar/spam.py` — add two functions next to `classify_ads_batch`.
- Test: `backend/tests/test_profile_scan.py`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_profile_scan.py`:

```python
# ── brand-lane disambiguation ─────────────────────────────────────────────────

def test_build_disambiguate_payload_includes_brand_and_sphere():
    from radar.spam import _build_disambiguate_payload
    p = _build_disambiguate_payload(["пост про #tanuki в игре"], brand_name="Тануки",
                                    sphere="сеть японских ресторанов")
    blob = p["system"] + p["messages"][0]["content"]
    assert "Тануки" in blob
    assert "сеть японских ресторанов" in blob
    assert "пост про #tanuki в игре" in blob

def test_disambiguate_brand_batch_fail_open_no_key():
    import radar.spam as sp
    old = sp.LLM_API_KEY; sp.LLM_API_KEY = ""
    try:
        from radar.spam import disambiguate_brand_batch
        assert disambiguate_brand_batch(["a", "b"], "Тануки", "еда") == [False, False]
    finally:
        sp.LLM_API_KEY = old

def test_disambiguate_brand_batch_empty():
    from radar.spam import disambiguate_brand_batch
    assert disambiguate_brand_batch([], "Тануки", "еда") == []
```

- [ ] **Step 2: Run to verify FAIL**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "disambiguate" -v`
Expected: FAIL — ImportError: cannot import name `_build_disambiguate_payload`.

- [ ] **Step 3: Implement both functions**

In `backend/radar/spam.py`, add directly above `def classify_ads_batch(`:

```python
def _build_disambiguate_payload(texts: list, brand_name: str, sphere: str = "") -> dict:
    """Anthropic request for brand-lane disambiguation. Each text already matched a
    brand keyword; decide whether it is really about the brand or an unrelated meaning
    of the word (homonym/off-topic). Default-keep: flag off-topic only when confident."""
    numbered = "\n".join(f"{i}. {(t or '')[:200]}" for i, t in enumerate(texts))
    sph = f' в сфере "{sphere}"' if sphere else ""
    system = (
        f'Каждый текст упоминает бренд "{brand_name}"{sph}. Реши: текст действительно '
        f'про ЭТОТ бренд — или это ДРУГОЕ значение слова (игра, животное, имя, оффтоп, '
        f'не относится к сфере бренда)? По умолчанию считай, что про бренд; помечай '
        f'off-topic ТОЛЬКО при явной уверенности. Отвечай ТОЛЬКО валидным JSON.'
    )
    user = (
        f"Тексты:\n{numbered}\n\n"
        f'Верни JSON-массив по одному объекту на текст: '
        f'[{{"i":0,"is_offtopic":false}}, ...]. is_offtopic=true только для явного оффтопа.'
    )
    return {"model": "claude-haiku-4-5-20251001", "max_tokens": 40 + len(texts) * 20,
            "system": system, "messages": [{"role": "user", "content": user}]}


def disambiguate_brand_batch(texts: list, brand_name: str, sphere: str = "") -> list:
    """Level-2 brand-lane filter: True = off-topic homonym (hide). Default-keep,
    fail-open: all False on no-key/error."""
    n = len(texts)
    if n == 0:
        return []
    if not LLM_API_KEY:
        return [False] * n

    import httpx

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=_build_disambiguate_payload(texts, brand_name, sphere),
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)

    try:
        data = _call()
    except Exception:
        try:
            data = _call()
        except Exception as e:
            log.warning("disambiguate_brand_batch failed: %s", e)
            return [False] * n

    flags = [False] * n
    try:
        for obj in data:
            i = obj.get("i")
            if isinstance(i, int) and 0 <= i < n:
                flags[i] = bool(obj.get("is_offtopic"))
    except Exception:
        return [False] * n
    return flags
```

- [ ] **Step 4: Run to verify PASS**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "disambiguate" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/spam.py backend/tests/test_profile_scan.py
git commit -m "feat: disambiguate_brand_batch — default-keep brand-lane homonym filter"
```

---

### Task 2: Wire disambiguation into the pipeline (replace the bypass)

**Files:**
- Modify: `backend/radar/pipeline.py` — `classify_and_draft` brand-lane block.
- Test: `backend/tests/test_profile_scan.py` — replace `test_brand_lane_bypasses_noise_judge`.

- [ ] **Step 1: Replace the obsolete bypass test with the new behavior test**

In `backend/tests/test_profile_scan.py`, DELETE the function `test_brand_lane_bypasses_noise_judge` and add in its place:

```python
def test_brand_lane_disambiguated_not_ad_judged(monkeypatch):
    """Brand-lane mentions go through disambiguation (off-topic homonyms hidden,
    real ones kept), NOT the ad/noise judge; niche lane still uses the noise judge."""
    from datetime import datetime, timezone
    import radar.spam as spam
    import radar.pipeline as pipeline
    from radar import db
    from radar.models import Brand, Mention
    # noise judge would hide everything if (wrongly) applied to the brand lane
    monkeypatch.setattr(spam, "classify_ads_batch", lambda texts, sphere="": [True] * len(texts))
    # disambiguation: first brand text off-topic, second on-topic
    monkeypatch.setattr(spam, "disambiguate_brand_batch",
                        lambda texts, brand_name, sphere="": [True, False][:len(texts)])
    monkeypatch.setattr(pipeline, "generate_draft", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "rescore_mention", lambda *a, **k: None)
    s = db.get_session()
    b = Brand(name="Тануки", user_id=1, keywords='["тануки"]', sphere="суши-рестораны")
    s.add(b); s.flush()

    def mk(src, pid, txt):
        m = Mention(brand_id=b.id, platform="tiktok", post_id=pid, author="a",
                    text=txt, source=src, is_spam=False,
                    created_at=datetime.now(timezone.utc))
        s.add(m); return m
    brand_off = mk("brand", "d-off", "прошёл уровень за тануки в игре сегодня")
    brand_on  = mk("brand", "d-on", "ужинали в тануки, роллы супер")
    niche_m   = mk("niche", "d-niche", "вообще про суши где-то в мире")
    s.flush()

    pipeline.classify_and_draft(s, b.id)
    s.refresh(brand_off); s.refresh(brand_on); s.refresh(niche_m)
    try:
        assert brand_off.is_spam is True    # off-topic homonym hidden
        assert brand_on.is_spam is False    # real brand mention kept
        assert niche_m.is_spam is True      # niche judged as noise
    finally:
        s.query(Mention).filter_by(brand_id=b.id).delete()
        s.delete(b); s.commit()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "disambiguated_not_ad" -v`
Expected: FAIL (current pipeline bypasses brand lane entirely, so `brand_off` stays False).

- [ ] **Step 3: Rewrite the brand-lane block in `classify_and_draft`**

In `backend/radar/pipeline.py`, replace the block that currently starts with the comment `# Level-2 noise filter:` and ends at `unclassified = kept` (the `from .spam import classify_ads_batch` block) with:

```python
    # Level-2 relevance filter. Brand-lane mentions matched a brand keyword, so they are
    # kept unless they are an off-topic homonym (default-keep disambiguation). Niche and
    # competitor lanes, where broad terms catch random content, go through the sphere
    # noise judge.
    from .spam import classify_ads_batch, disambiguate_brand_batch
    if unclassified:
        sphere = getattr(brand, "sphere", "") or ""
        brand_ms = [m for m in unclassified if m.source == "brand"]
        other_ms = [m for m in unclassified if m.source != "brand"]
        noise = set()
        if brand_ms:
            off = disambiguate_brand_batch([m.text for m in brand_ms],
                                           brand_name=brand.name, sphere=sphere)
            for m, is_off in zip(brand_ms, off):
                if is_off:
                    m.is_spam = True
                    noise.add(id(m))
        if other_ms:
            flags = classify_ads_batch([m.text for m in other_ms], sphere=sphere)
            for m, is_ad in zip(other_ms, flags):
                if is_ad:
                    m.is_spam = True
                    noise.add(id(m))
        kept = [m for m in unclassified if id(m) not in noise]
        session.commit()
        unclassified = kept
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -q`
Expected: all pass (new disambiguation test + everything else).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/pipeline.py backend/tests/test_profile_scan.py
git commit -m "feat: brand lane uses default-keep disambiguation instead of blanket bypass"
```

---

### Task 3: Intent reach — generation + opportunity labelling

**Files:**
- Modify: `backend/radar/pipeline.py` — add `_looks_like_intent`; update `opportunity_for`.
- Modify: `backend/radar/api.py` — intent-phrase guidance in `_build_suggest_payload` and `_profile_with_claude`.
- Test: `backend/tests/test_profile_scan.py`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_profile_scan.py`:

```python
# ── intent reach ──────────────────────────────────────────────────────────────

def test_looks_like_intent_true():
    from radar.pipeline import _looks_like_intent
    assert _looks_like_intent("посоветуйте, где вкусно поесть?") is True
    assert _looks_like_intent("куда сходить на выходных?") is True

def test_looks_like_intent_false():
    from radar.pipeline import _looks_like_intent
    assert _looks_like_intent("купил роллы вчера, очень вкусно") is False
    assert _looks_like_intent("просто красивое видео про суши") is False

def test_opportunity_niche_intent_vs_plain():
    from radar.pipeline import opportunity_for
    from radar.models import Mention
    intent = Mention(source="niche", text="подскажите, куда сходить поесть?")
    plain  = Mention(source="niche", text="люблю японскую кухню")
    o_intent = opportunity_for(intent)
    o_plain  = opportunity_for(plain)
    assert "ищет" in o_intent          # stronger intent hint
    assert o_intent != o_plain
    assert o_plain is not None         # plain niche keeps the existing hint

def test_opportunity_competitor_unchanged():
    from radar.pipeline import opportunity_for
    from radar.models import Mention
    m = Mention(source="competitor", competitor="Якитория", text="был в якитории")
    assert "Якитория" in opportunity_for(m)
```

- [ ] **Step 2: Run to verify FAIL**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -k "intent or opportunity" -v`
Expected: FAIL — ImportError: cannot import name `_looks_like_intent`.

- [ ] **Step 3: Add `_looks_like_intent` and update `opportunity_for`**

In `backend/radar/pipeline.py`, add above `def opportunity_for(`:

```python
_INTENT_CUES = ("куда", "где", "посовет", "подскажите", "что попробовать",
                "что выбрать", "стоит ли", "который лучше")

def _looks_like_intent(text: str) -> bool:
    """Recommendation-seeking / where-to-go post — sphere-agnostic. Needs a question
    mark plus a recommendation cue."""
    t = (text or "").lower()
    return "?" in t and any(c in t for c in _INTENT_CUES)
```

Then change `opportunity_for` so the `niche` branch upgrades intent posts:

```python
def opportunity_for(m: Mention) -> Optional[str]:
    if m.source == "competitor":
        who = m.competitor or "конкурента"
        return f"Аудитория обсуждает {who} — момент предложить ваш бренд как альтернативу."
    if m.source == "niche":
        if _looks_like_intent(m.text):
            return "Человек ищет, куда пойти / что выбрать — отличный момент предложить бренд нативно."
        return "Тематическая аудитория без упоминания бренда — хороший момент зайти нативно."
    return None
```

- [ ] **Step 4: Add intent-phrase guidance to both suggest prompts**

In `backend/radar/api.py`, in `_build_suggest_payload`, replace the line:

```python
        f'niche_keywords — 15-25 (тематика индустрии + смежные интересы ЦА); '
```
with:
```python
        f'niche_keywords — 15-25 (тематика индустрии + смежные интересы ЦА + intent-фразы '
        f'по сфере: как люди ищут такое, напр. для еды «где поесть», «куда сходить на '
        f'выходных», «посоветуйте ресторан»); '
```

In `_profile_with_claude`, replace the line:

```python
        'niche_keywords подбери ШИРОКО: тематика + индустрия + смежные интересы ЦА.\n'
```
with:
```python
        'niche_keywords подбери ШИРОКО: тематика + индустрия + смежные интересы ЦА + '
        'intent-фразы по сфере (как люди ищут такое: для еды «где поесть», «куда сходить '
        'на выходных», «посоветуйте ресторан»).\n'
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_profile_scan.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/radar/pipeline.py backend/radar/api.py backend/tests/test_profile_scan.py
git commit -m "feat: intent reach — sphere intent phrases in niche + stronger opportunity hint"
```

---

### Task 4: Re-verify on the Тануки brand (operational)

Not TDD — confirms the homonym is dropped and real mentions stay.

- [ ] **Step 1: Restart backend with the new code**

```bash
cd backend && pkill -f "uvicorn radar.api:app"; sleep 1
(uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &)
sleep 4
```
Confirm health 200 via a python3/urllib GET to `http://127.0.0.1:8000/health` (a hook intercepts curl).

- [ ] **Step 2: Reset brand-10 mentions for a clean re-judge and re-run the pipeline**

```bash
cd backend && python3 - <<'PY'
import sqlite3
db = sqlite3.connect("echo_radar.db")
db.execute("UPDATE mentions SET is_spam=0, category=NULL WHERE brand_id=10")
db.commit(); print("reset", db.total_changes); db.close()
PY
python3 - <<'PY'
from radar.db import get_session
from radar.pipeline import classify_and_draft
print(classify_and_draft(get_session(), 10))
PY
```

- [ ] **Step 3: Verify homonyms gone, real mentions kept**

```bash
cd backend && python3 - <<'PY'
import sqlite3
db = sqlite3.connect("echo_radar.db"); db.row_factory = sqlite3.Row
vis = db.execute("SELECT COUNT(*) c FROM mentions WHERE brand_id=10 AND is_spam=0").fetchone()["c"]
print("visible:", vis)
print("--- visible brand-lane ---")
for r in db.execute("SELECT author, substr(text,1,80) t FROM mentions WHERE brand_id=10 AND is_spam=0 AND source='brand'"):
    print(f"@{r['author']}: {r['t']}")
PY
```
Expected: real Тануки restaurant mentions remain visible; obvious game/off-topic `#tanuki` posts are now hidden. If a real mention got hidden, that is a disambiguation false-positive — review the prompt before patching blindly.

- [ ] **Step 4: No commit** — DB data only.

---

## Notes
- `LLM_API_KEY` / `TIKHUB_TOKEN` in `backend/.env`.
- A `curl`/`wget` hook redirects to context-mode — use `python3` for HTTP.
- Brand-lane disambiguation adds batched Haiku calls; fail-open + default-keep keep it safe.
