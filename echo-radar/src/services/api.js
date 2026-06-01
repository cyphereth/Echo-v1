// Base URL: empty in prod (same origin), override via VITE_API_BASE for custom setups
const BASE = import.meta.env.VITE_API_BASE ?? '';

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) throw new Error(`${opts.method ?? 'GET'} ${path} → ${res.status}`);
  return res.json();
}

// ── Brands ──────────────────────────────────────────────────────────────────

export const getBrands = () => req('/brands');
export const getBrand  = (id) => req(`/brands/${id}`);

// ── Inbox ────────────────────────────────────────────────────────────────────

export const getInbox = (brandId) => req(`/inbox?brand_id=${brandId}`);

// ── Mentions ──────────────────────────────────────────────────────────────────

export const getMention = (id) => req(`/mentions/${id}`);

export const postAction = (id, action, editedDraft = null) =>
  req(`/mentions/${id}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, ...(editedDraft ? { draft: editedDraft } : {}) }),
  });

// ── Normalize backend → frontend shape ───────────────────────────────────────

// Backend lane: "pr" | "smm" | "none"  →  frontend: "PR" | "SMM" | "none"
const LANE_MAP = { pr: 'PR', smm: 'SMM', none: 'none' };

// Relative time label from ISO timestamp
function ago(isoString) {
  if (!isoString) return '—';
  const diff = Date.now() - new Date(isoString).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60)  return `${m || 1} мин`;
  const h = Math.floor(m / 60);
  if (h < 24)  return `${h} ч`;
  return `${Math.floor(h / 24)} д`;
}

export function normalizeMention(m) {
  const views = m.views ?? 0;
  // Build a minimal sparkline from whatever snapshot data we have
  // Backend may return snapshots[] on detail view; on list view we use a flat line
  const snapViews = m.snapshots?.map(s => s.views) ?? [Math.round(views * 0.4), Math.round(views * 0.7), views];
  return {
    id:         String(m.id),
    platform:   m.platform,
    author:     m.author,
    followers:  m.followers ?? 0,
    ago:        ago(m.created_at),
    text:       m.text,
    severity:   Math.round(m.severity ?? 0),
    phase:      m.phase === 'peaked' ? 'declining' : (m.phase ?? 'unknown'),
    tone:       m.tone ?? 'neutral',
    confidence: m.confidence ?? 0.5,
    category:   m.category ?? 'neutral',
    lane:       LANE_MAP[m.lane] ?? 'none',
    hot:        m.is_hot ?? false,
    views:      snapViews,
    peakViews:  fmtNum(Math.max(...snapViews)),
    rate:       m.velocity != null ? fmtVelocity(m.velocity) : '—',
    draft:      m.draft ?? null,
    humor:      m.draft_flag === 'humor_manual',
    status:     m.status ?? 'new',   // API may add status later; default new
  };
}

function fmtNum(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000)    return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
function fmtVelocity(v) {
  const abs = Math.abs(Math.round(v));
  return v >= 0 ? `+${abs}/мин` : `−${abs}/мин`;
}
