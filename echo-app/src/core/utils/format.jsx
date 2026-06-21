// ============================================================================
// Shared formatters & tone maps — single source of truth.
// Раньше sevTone / fmtNum / agoStr / getLaneColor / getLaneLabel копипастились
// в 4+ файлах (Feed, Queue, Detail×2, BrandApp, NewsApp). Теперь живут тут.
// Канон цвета — project/ui_kits/app/data.jsx.
// ============================================================================

// severity → warm signal color + russian label.
// ВАЖНО: «спокойствие как фон, срочность как точка». calm-ветка возвращает
// ЦИАН (бренд), а не --sev-calm (зелёный) — зелёный прибережён для «отправлено».
export function sevTone(s) {
  const v = Number(s) || 0;
  if (v >= 75) return { key: 'critical', color: '#FF4D5E', bright: '#FF7A87', ghost: 'rgba(255,77,94,.14)', line: 'rgba(255,77,94,.38)', label: 'Залетает' };
  if (v >= 45) return { key: 'rising',   color: '#FFB23E', bright: '#FFC871', ghost: 'rgba(255,178,62,.14)', line: 'rgba(255,178,62,.36)', label: 'Растёт' };
  return { key: 'calm', color: '#2BB3C7', bright: '#57D2E2', ghost: 'rgba(43,179,199,.12)', line: 'rgba(43,179,199,.32)', label: 'Под контролем' };
}

export const PHASE = {
  rising:    { label: 'растёт',   icon: 'trendingUp',   color: '#FFC871' },
  declining: { label: 'затухает', icon: 'trendingDown', color: '#7E91A6' },
  unknown:   { label: 'не ясно',  icon: 'activity',     color: '#7E91A6' },
};

export const TONE = {
  negative: { label: 'Негатив',    color: '#FF7A87' },
  neutral:  { label: 'Нейтрально', color: '#97A9BE' },
  positive: { label: 'Позитив',    color: '#34D8A0' },
};

// Числа для человека: 1.2k просмотров, +340/час. Точные значения — в mono.
export function fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(n);
}

// «5 мин назад» / «2 ч» / «3 д» — относительное время от created_at (ISO или ms).
export function agoStr(ts) {
  if (!ts) return '';
  const then = typeof ts === 'number' ? ts : Date.parse(ts);
  if (!then || isNaN(then)) return '';
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1)  return 'только что';
  if (mins < 60) return mins + ' мин';
  const hrs = Math.round(mins / 60);
  if (hrs < 24)  return hrs + ' ч';
  const days = Math.round(hrs / 24);
  return days + ' д';
}

// Lane → цвет + русская метка. brand|competitor|niche — это source-полосы бренда.
export function getLaneColor(lane) {
  if (lane === 'pr' || lane === 'brand')       return 'var(--sev-critical-bright)';
  if (lane === 'smm' || lane === 'niche')      return 'var(--brand-bright)';
  if (lane === 'competitor')                   return 'var(--lane-competitor)';
  return 'var(--fg-3)';
}

export function getLaneLabel(lane) {
  if (lane === 'pr' || lane === 'PR')          return 'PR · срочно';
  if (lane === 'smm' || lane === 'SMM')        return 'SMM';
  if (lane === 'brand')                        return 'Мой бренд';
  if (lane === 'competitor')                   return 'Конкуренты';
  if (lane === 'niche')                        return 'Ниша';
  return '—';
}
