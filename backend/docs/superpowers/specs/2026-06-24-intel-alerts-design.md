# Intel Alerts & Anomaly Push — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorm) — pending implementation plan
**Contour:** closed / military-intelligence (`intel` domain)

## 1. Context & Goal

The `intel` domain already detects anomalies at the **story** level: `radar/core/anomalies.py::detect_anomaly` sets `story.is_anomaly` when the latest timeline bucket shows a volume spike **and** (a sentiment drop **or** a source influx). `aggregate.compute_overview` surfaces those flagged stories as an `alerts` list, but only when the client polls `/intel/overview`. There is **no persistent alert record, no direction-level burst detection, and no real-time push** — the operator has to refresh to learn a direction lit up.

**Goal:** Detect activity bursts at both the **story** and **direction** levels, persist them as deduplicated `IntelAlert` rows, and push them to the operator in real time over the existing SSE live stream — surfaced as a corner toast plus a notification-bell center with unread history.

## 2. Scope & Non-Goals

**In scope:**
- New `IntelAlert` table: typed, scoped (story/direction), with magnitude, message, fire time, and an acknowledged flag.
- Story-level alerts: emitted when a story transitions into anomaly (or stays anomalous past the cooldown).
- Direction-level burst detection: a new aggregate over per-direction hourly mention counts, reusing the existing anomaly env-tunables.
- Cooldown dedup so one sustained burst produces one alert, not a stream.
- Delivery over the **existing** `/intel/stream/live` SSE endpoint as a named `alert` event (no second connection).
- REST: list alerts, acknowledge one, acknowledge all.
- Frontend: SSE-driven toast + a notification bell with unread badge and dropdown; initial unread load on mount.

**Non-goals (deferred):**
- Per-user alert preferences / mute rules / per-direction subscriptions.
- External notification channels (email, Telegram push, webhooks).
- ML/learned thresholds — detection stays on the existing deterministic env-tunables.
- Alert severity tiers beyond the `magnitude` float (UI may bucket it later).
- Brand-domain alerts (this spec is `intel`-only; the detection core is already generic and reusable later).

## 3. Data Model — `IntelAlert`

New table in `radar/intel/models.py`:

| field | type | purpose |
|---|---|---|
| `id` | int PK | autoincrement; the SSE tail orders/filters by it |
| `scope` | str | `"story"` or `"direction"` |
| `direction_id` | FK→`IntelDirection`, nullable | always populated (a story alert copies its story's direction) |
| `story_id` | FK→`IntelStory`, nullable | populated only when `scope="story"` |
| `kind` | str | `"spike"`, `"sentiment"`, `"source_influx"`, `"direction_burst"` |
| `magnitude` | float | spike pct / factor — drives ordering and message text |
| `title` | str | story title or direction name |
| `message` | str | human-readable (e.g. `"Всплеск ×4 по направлению Артёмовск"`) |
| `fired_at` | datetime (UTC) | when it fired |
| `acknowledged_at` | datetime (UTC), nullable | `NULL` = unread |

**Indexes:** PK on `id`; composite `(scope, direction_id, fired_at)` and `(scope, story_id, fired_at)` to make the cooldown lookup cheap.

**Migration:** additive `create_table` only — no changes to existing tables. Registered the same way the other `intel` tables are (imported so `Base.metadata` sees it).

## 4. Detection — `radar/intel/alerts.py` (new module)

Runs inside the ticker's PROCESS phase (`passes.run_intel_tick`, default 180s), immediately after clustering + `detect_anomaly`:

- **Story alerts.** `detect_anomaly` already sets `story.is_anomaly`. We emit an alert when a story is anomalous **and** no alert for that `(scope="story", story_id, kind)` exists within `ALERT_COOLDOWN_H`. `kind` is derived from which condition fired (volume spike / sentiment drop / source influx); `magnitude` from `_spike_pct` of the story's points.
- **Direction bursts.** New `detect_direction_burst(session, direction, window)`: build hourly mention counts for the direction (same bucketing `aggregate` uses), and fire `kind="direction_burst"` when the latest bucket is `>= ANOMALY_VOLUME_FACTOR ×` the mean of prior buckets **and** `>= ANOMALY_MIN_VOLUME` (absolute floor), with at least `ANOMALY_MIN_BUCKETS` baseline buckets. `magnitude` = the computed spike pct.

**Cooldown dedup.** A single helper `_emit(session, scope, ref_id, kind, ...)` checks for an existing row of the same `(scope, ref_id, kind)` with `fired_at >= now - ALERT_COOLDOWN_H` (env, default `6`). If found, it no-ops; otherwise it inserts. This is the single insertion path — both detectors call it.

**Tunables:** reuse `ANOMALY_VOLUME_FACTOR`, `ANOMALY_MIN_VOLUME`, `ANOMALY_MIN_BUCKETS` from `core/anomalies.py`; add `ALERT_COOLDOWN_H` (default 6).

## 5. Delivery — extend the existing SSE stream

`/intel/stream/live`'s `event_gen` currently tails `IntelMention` by `id`. We add a **second tail** in the same loop:

- New query param `after_alert_id` (mirrors `after_id`; makes reconnect lossless).
- Each cycle also runs `SELECT IntelAlert WHERE id > last_alert_id ORDER BY id`.
- Mentions stay the default frame (`data: {...}`); alerts are emitted as a **named** SSE event: `event: alert\ndata: {json}\n\n`.
- The client opens **one** `EventSource`: `onmessage` handles mentions, `addEventListener("alert", …)` handles alerts. The existing watchdog/visibility-reconnect logic is reused; we only thread the last seen `alert_id` into the reconnect URL.

No in-memory pub/sub bus is introduced — DB-tailing matches the existing architecture and stays reconnect-safe.

## 6. REST — history & acknowledgement

- `GET /intel/alerts?unread=true&limit=50` — list alerts (bell dropdown + initial load), newest first.
- `POST /intel/alerts/{id}/ack` — set `acknowledged_at = now`.
- `POST /intel/alerts/ack-all` — acknowledge all unread.

`aggregate.compute_overview` is switched to read its `alerts` block from `IntelAlert` (newest unacked first) instead of recomputing from `is_anomaly`, so the IntelHome block, the bell, and the stream share **one source of truth**.

## 7. Frontend

- **Stream hook** (where the current `EventSource` lives): add an `alert` listener that pushes into an alerts store and triggers a toast.
- **`AlertToast`** — corner popup on arrival, auto-dismiss ~8s, click navigates to the story/direction.
- **`AlertBell`** — header icon in `IntelApp` with an unread badge, a dropdown list, and an "acknowledge all" action; calls the ack endpoints.
- **Mount load** — fetch `GET /intel/alerts?unread=true` so unread history is present before the first live alert.

## 8. Testing (TDD)

- `test_intel_alerts.py`:
  - direction burst fires / does not fire (spike-only vs burst, insufficient history);
  - cooldown dedup — a repeat within the window inserts no new row;
  - story alert fires on transition into anomaly; `kind` reflects the triggering condition;
  - ack flow sets `acknowledged_at`; `ack-all` clears all unread.
- SSE test (extend `test_intel_realtime` or new): after `after_alert_id`, a new `IntelAlert` row is delivered as an `event: alert` frame.
- API test: `/intel/alerts` listing + filtering, `ack`, `ack-all`.

## 9. Risks & Notes

- **Detection latency:** alerts fire on the 180s tick, not per-event. Acceptable — bursts are evaluated on hourly buckets; SSE delivers the row to the browser within ~1s of insertion.
- **Cooldown calibration:** 6h default may be too long/short on real traffic; it is env-tunable (`ALERT_COOLDOWN_H`) and validated against live data after rollout.
- **Overview coupling:** switching `compute_overview` to read `IntelAlert` changes the existing `alerts` payload source; the field shape is preserved so the current IntelHome block keeps rendering.
