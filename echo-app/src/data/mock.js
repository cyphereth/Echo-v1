// Helpers for lane display — used by Feed, Queue, Detail components.

export function getLaneColor(lane) {
  if (lane === 'competitor') return 'var(--warn)';
  if (lane === 'niche')      return 'var(--info, #6c8ebf)';
  return 'var(--brand)';
}

export function getLaneLabel(lane, competitor) {
  if (lane === 'competitor') return competitor ? `vs ${competitor}` : 'Конкурент';
  if (lane === 'niche')      return 'Ниша';
  return 'Мой бренд';
}
