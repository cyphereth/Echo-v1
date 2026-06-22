// Intel API layer — mock-first. INTEL_USE_MOCK=true отдаёт моки из data/mock.js;
// false — ходит в /intel/* (бэкенд intel-домена, строится отдельно).
// Контракт идентичен (§6 спеки), переключение прозрачное для компонентов.
import { request } from '../../core/api/client';
import { INTEL_USE_MOCK, mockApi } from './data/mock';

const passthrough = (path, params) => {
  const qs = params ? '?' + new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  ).toString() : '';
  return request(`/intel/${path}${qs}`);
};

export const intelApi = {
  overview:  (window = '24h') => INTEL_USE_MOCK ? mockApi.overview(window) : passthrough('overview', { window }),
  stream:    (params)         => INTEL_USE_MOCK ? mockApi.stream(params || {}) : passthrough('stream', params),
  stories:   (params)         => INTEL_USE_MOCK ? mockApi.stories(params || {}) : passthrough('stories', params),
  story:     (id)             => INTEL_USE_MOCK ? mockApi.story(id) : request(`/intel/stories/${id}`),
  directions:(window = '24h') => INTEL_USE_MOCK ? mockApi.directions() : passthrough('directions', { window }),
  direction: (key, window)    => INTEL_USE_MOCK ? mockApi.direction(key) : request(`/intel/directions/${key}?window=${window || '24h'}`),
  search:    (q)              => INTEL_USE_MOCK ? mockApi.search(q) : passthrough('search', { q }),
  sources:   (params)         => passthrough('sources', params),
  addSource: (body)           => request('/intel/sources', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }),
  deleteSource: (id)          => request('/intel/sources/' + id, { method: 'DELETE' }),
};

// ── Витринные форматтеры ────────────────────────────────────────────────────
export const CREDIBILITY = {
  verified:   { label: 'Подтверждено', color: '#34D8A0', bg: 'rgba(52,216,160,.13)', border: 'rgba(52,216,160,.34)' },
  likely:     { label: 'Вероятно',     color: '#57D2E2', bg: 'rgba(87,210,226,.12)', border: 'rgba(87,210,226,.30)' },
  unverified: { label: 'Не подтверждено', color: '#97A9BE', bg: 'rgba(151,169,190,.10)', border: 'rgba(151,169,190,.25)' },
  fake:       { label: 'Дезинформация', color: '#FF4D5E', bg: 'rgba(255,77,94,.14)', border: 'rgba(255,77,94,.38)' },
  unrated:    { label: 'Без оценки', color: '#5C6E83', bg: 'rgba(92,110,131,.10)', border: 'rgba(92,110,131,.20)' },
};

export const SIDE = {
  ru: { label: 'РФ',   color: '#FF7A87' },
  ua: { label: 'УКР',  color: '#57D2E2' },
  by: { label: 'БЛР',  color: '#9AA7B5' },
  mx: { label: 'MX',   color: '#9AA7B5' },
};

export function spikeLevel(pct) {
  if (pct >= 250) return { label: 'ВЗЛЁТ', color: '#FF4D5E' };
  if (pct >= 150) return { label: 'РЕЗКИЙ', color: '#FF7A87' };
  if (pct >= 100) return { label: 'РОСТ', color: '#FFB23E' };
  return { label: 'ФОН', color: '#7E91A6' };
}

export function activityLevel(level) {
  if (level >= 75) return { label: 'КРИТ', color: '#FF4D5E' };
  if (level >= 50) return { label: 'ВЫСОК', color: '#FFB23E' };
  if (level >= 25) return { label: 'СРЕДНИЙ', color: '#57D2E2' };
  return { label: 'ТИХО', color: '#7E91A6' };
}

export function agoStrShort(iso) {
  if (!iso) return '';
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (mins < 1) return 'сейчас';
  if (mins < 60) return `${mins}м`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}ч`;
  return `${Math.floor(hrs / 24)}д`;
}

export { DIRECTION_NAMES } from './data/mock';
