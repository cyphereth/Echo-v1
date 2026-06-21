// ============================================================================
// Intel contour — MOCK data matching the §6 data contract.
// Реалистичный военный контент: направления (секторы), стороны (ru/ua),
// верификация, spike-детекция. Фронт строится против этих моков;
// бэкенд intel-домена позже будет отдавать тот же shape через /intel/*.
// Переключатель mock→live: INTEL_USE_MOCK ниже.
// ============================================================================

// true = отдавать моки локально; false = ходить в /intel/* (когда бэкенд готов)
export const INTEL_USE_MOCK = true;

// ── helpers ─────────────────────────────────────────────────────────────────
const now = Date.now();
const ago = (mins) => new Date(now - mins * 60000).toISOString();
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

export const DIRECTIONS_TAXONOMY = [
  'kursk', 'zaporizhzhia', 'kharkiv', 'donetsk', 'kherson',
  'belgorod', 'crimea', 'sumy',
];

export const DIRECTION_NAMES = {
  kursk: 'Курское направление',
  zaporizhzhia: 'Запорожское направление',
  kharkiv: 'Харьковское направление',
  donetsk: 'Донецкое направление',
  kherson: 'Херсонское направление',
  belgorod: 'Белгородское направление',
  crimea: 'Крым',
  sumy: 'Сумское направление',
};

const CRED = ['verified', 'likely', 'verified', 'likely', 'unverified', 'fake'];

// ── Story summaries ─────────────────────────────────────────────────────────
export const MOCK_STORIES = [
  {
    id: 's1', title: 'Массированный удар БПЛА по энергетической инфраструктуре',
    direction: 'zaporizhzhia', sides: ['ru', 'ua'],
    source_count: 14, post_count: 87, verified: true,
    credibility: 'verified', credibility_note: 'Подтверждено 14 независимыми источниками обеих сторон',
    spike_pct: 340, sparkline: [4, 6, 5, 12, 28, 41, 87], last_seen_at: ago(8),
  },
  {
    id: 's2', title: 'Продвижение в районе Суджи — контратака',
    direction: 'kursk', sides: ['ru', 'ua'],
    source_count: 9, post_count: 52, verified: true,
    credibility: 'likely', credibility_note: 'Геолокация подтверждает район, масштаб уточняется',
    spike_pct: 210, sparkline: [3, 5, 8, 14, 22, 31, 52], last_seen_at: ago(14),
  },
  {
    id: 's3', title: 'Обстрел приграничных населённых пунктов',
    direction: 'belgorod', sides: ['ru'],
    source_count: 6, post_count: 34, verified: false,
    credibility: 'unverified', credibility_note: 'Источники одной стороны, ждём подтверждения',
    spike_pct: 95, sparkline: [2, 3, 4, 6, 9, 14, 34], last_seen_at: ago(22),
  },
  {
    id: 's4', title: 'Активность ППО над акваторией',
    direction: 'crimea', sides: ['ru', 'ua'],
    source_count: 11, post_count: 68, verified: true,
    credibility: 'verified', credibility_note: 'Видео с двух точек совпадает по времени',
    spike_pct: 175, sparkline: [5, 7, 9, 15, 24, 40, 68], last_seen_at: ago(11),
  },
  {
    id: 's5', title: 'Перегруппировка сил у Купянска',
    direction: 'kharkiv', sides: ['ru', 'ua'],
    source_count: 5, post_count: 19, verified: false,
    credibility: 'likely', credibility_note: 'OSINT-анализ спутниковых снимков',
    spike_pct: 60, sparkline: [2, 3, 3, 4, 7, 12, 19], last_seen_at: ago(45),
  },
  {
    id: 's6', title: 'Позиционные бои под Авдеевкой',
    direction: 'donetsk', sides: ['ru', 'ua'],
    source_count: 8, post_count: 41, verified: true,
    credibility: 'verified', credibility_note: 'Подтверждено военкорами обеих сторон',
    spike_pct: 120, sparkline: [4, 6, 8, 11, 18, 27, 41], last_seen_at: ago(33),
  },
  {
    id: 's7', title: 'Дезинформация о потерях на южном фланге',
    direction: 'zaporizhzhia', sides: ['ua'],
    source_count: 3, post_count: 27, verified: false,
    credibility: 'fake', credibility_note: 'Видео 2023 года, переиспользовано. Геолокация не совпадает.',
    spike_pct: 280, sparkline: [1, 2, 4, 9, 18, 22, 27], last_seen_at: ago(6),
  },
  {
    id: 's8', title: 'Удар по логистическому узлу',
    direction: 'kherson', sides: ['ru', 'ua'],
    source_count: 7, post_count: 38, verified: true,
    credibility: 'likely', credibility_note: 'Тепловые сигнатуры подтверждают, объект уточняется',
    spike_pct: 155, sparkline: [3, 4, 6, 10, 16, 24, 38], last_seen_at: ago(19),
  },
];

// ── Events (stream) ─────────────────────────────────────────────────────────
const EVENT_TEXTS = {
  ru: [
    'Отражена атака БПЛА, работает ППО',
    'Уничтожена группа диверсантов на рубеже',
    'Удар по скоплению техники противника',
    'Перехвачена РСЗО над населённым пунктом',
    'Взяты под контроль высоты в секторе',
  ],
  ua: [
    'Зафіксовано рух колони техніки',
    'Уразлено командний пункт',
    'Відбито штурм у напрямку',
    'Знищено склад БК',
    'Зафіксовано перегрупування сил противника',
  ],
};

export const MOCK_EVENTS = Array.from({ length: 40 }, (_, i) => {
  const side = pick(['ru', 'ua']);
  const direction = pick(DIRECTIONS_TAXONOMY);
  const minsAgo = Math.floor(i * 1.5 + Math.random() * 3);
  const cred = pick(CRED);
  return {
    id: `e${i}`, platform: pick(['telegram', 'telegram', 'web']),
    author: side === 'ru' ? pick(['rybar', 'voin_dv', 'warhistory', 't.me/infantmilio']) : pick(['deepstate', 'warmonitor', 't.me/bakhmut_ua']),
    side, direction,
    text: pick(EVENT_TEXTS[side]),
    url: `https://t.me/c/${1000 + i}`,
    created_at: ago(minsAgo),
    verified: cred === 'verified' || cred === 'likely',
  };
});

// ── Directions (operational board) ──────────────────────────────────────────
export const MOCK_DIRECTIONS = DIRECTIONS_TAXONOMY.map((key, i) => {
  const dirStories = MOCK_STORIES.filter(s => s.direction === key);
  const events_count = MOCK_EVENTS.filter(e => e.direction === key).length + Math.floor(Math.random() * 20);
  const activity = [88, 72, 64, 58, 45, 38, 31, 22][i] || Math.floor(Math.random() * 100);
  const spike = dirStories.length ? Math.max(...dirStories.map(s => s.spike_pct)) : Math.floor(Math.random() * 80);
  const lastEvent = MOCK_EVENTS.find(e => e.direction === key) || MOCK_EVENTS[0];
  const cred = dirStories.length
    ? (dirStories.filter(s => s.credibility === 'verified').length >= dirStories.length / 2 ? 'verified' : 'likely')
    : 'unrated';
  return {
    key, name: DIRECTION_NAMES[key],
    activity_level: activity, spike_pct: spike, events_count,
    dominant_credibility: cred,
    last_event: { text: lastEvent.text, at: lastEvent.created_at, source: lastEvent.author },
  };
});

// ── Alerts ──────────────────────────────────────────────────────────────────
export const MOCK_ALERTS = [
  { id: 'a1', story_id: 's1', direction: 'zaporizhzhia', kind: 'spike', magnitude: 340, message: 'Активность по сюжету выросла на 340% за час', at: ago(7) },
  { id: 'a2', story_id: 's7', direction: 'zaporizhzhia', kind: 'fake', magnitude: 280, message: 'Вероятная дезинформация: переиспользованное видео', at: ago(5) },
  { id: 'a3', story_id: 's2', direction: 'kursk', kind: 'spike', magnitude: 210, message: 'Резкий рост упоминаний контратаки', at: ago(13) },
  { id: 'a4', story_id: 's4', direction: 'crimea', kind: 'spike', magnitude: 175, message: 'Активность ППО, рост охвата', at: ago(10) },
];

// ── Story detail (points + sources + events) ────────────────────────────────
export function storyDetail(id) {
  const s = MOCK_STORIES.find(x => x.id === id);
  if (!s) return null;
  const buckets = Array.from({ length: 24 }, (_, i) => {
    const base = Math.max(1, Math.round((s.sparkline[i % s.sparkline.length] || 1) * (0.6 + Math.random() * 0.8)));
    return {
      bucket_start: ago((23 - i) * 60),
      mention_count: base,
      source_count: Math.max(1, Math.round(base * 0.18 + Math.random() * 2)),
    };
  });
  const sideRoll = (s.sides.length > 1 ? ['ru', 'ua'] : s.sides);
  const sources = Array.from({ length: s.source_count }, (_, i) => ({
    name: pick(['rybar', 'deepstate', 'warmonitor', 'voin_dv', 't.me/bakhmut_ua', 'Reuters', 'Meduza', 'radius']),
    side: pick(sideRoll),
    count: Math.max(1, Math.round(s.post_count / s.source_count * (0.5 + Math.random()))),
    last_at: ago(Math.floor(Math.random() * 60)),
    url: `https://t.me/c/${2000 + i}`,
  })).sort((a, b) => b.count - a.count);
  const events = MOCK_EVENTS.filter(e => e.direction === s.direction).slice(0, 8);
  return {
    ...s,
    summary_text: `${s.title}. ${s.credibility_note}. Активность выросла на ${s.spike_pct}% относительно базовой линии за последние часы. Источники: ${s.source_count} (${s.sides.join(', ')} сторон).`,
    points: buckets,
    sources,
    events,
  };
}

// ── Overview ────────────────────────────────────────────────────────────────
// window — для сигнатурной совместимости с реальным /intel/overview?window=;
// мок игнорирует окно (всегда полные данные).
// eslint-disable-next-line no-unused-vars
export function overview(window) {
  const hot = [...MOCK_STORIES].sort((a, b) => b.spike_pct - a.spike_pct).slice(0, 5);
  const top = [...MOCK_STORIES].sort((a, b) => b.post_count - a.post_count).slice(0, 5);
  return {
    kpis: {
      events: MOCK_EVENTS.length + 12,
      active_stories: MOCK_STORIES.length,
      spiking_dirs: MOCK_DIRECTIONS.filter(d => d.spike_pct > 100).length,
    },
    hot, alerts: MOCK_ALERTS, top_stories: top,
  };
}

// ── Mock API (drop-in for real /intel/* later) ──────────────────────────────
const delay = (ms) => new Promise(r => setTimeout(r, ms));

export const mockApi = {
  overview: async (window) => { await delay(120); return overview(window); },
  stream: async (params = {}) => {
    await delay(100);
    let evs = [...MOCK_EVENTS].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    if (params.direction) evs = evs.filter(e => e.direction === params.direction);
    return evs.slice(0, params.limit || 30);
  },
  stories: async (params = {}) => {
    await delay(120);
    let list = [...MOCK_STORIES];
    if (params.direction) list = list.filter(s => s.direction === params.direction);
    if (params.side) list = list.filter(s => s.sides.includes(params.side));
    if (params.verified === 'true' || params.verified === true) list = list.filter(s => s.verified);
    if (params.sort === 'recency') list.sort((a, b) => new Date(b.last_seen_at) - new Date(a.last_seen_at));
    else list.sort((a, b) => b.spike_pct - a.spike_pct);
    return list.slice(0, params.limit || 30);
  },
  story: async (id) => { await delay(100); return storyDetail(id); },
  directions: async () => { await delay(120); return [...MOCK_DIRECTIONS].sort((a, b) => b.activity_level - a.activity_level); },
  direction: async (key) => {
    await delay(120);
    const d = MOCK_DIRECTIONS.find(x => x.key === key);
    return {
      direction: d,
      stories: MOCK_STORIES.filter(s => s.direction === key),
      stream: MOCK_EVENTS.filter(e => e.direction === key).slice(0, 12),
    };
  },
  search: async (q) => {
    await delay(100);
    const ql = q.toLowerCase();
    return MOCK_STORIES.filter(s => s.title.toLowerCase().includes(ql) || s.direction.includes(ql));
  },
};
