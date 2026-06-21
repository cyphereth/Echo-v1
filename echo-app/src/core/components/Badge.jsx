// Shared badge style helper and badge components.
// Цвета — канон дизайн-системы (calm-зелёный для «проверено», critical-алый для «требует проверки»).
import { Icon } from './icons';

export const badgeStyle = (bg, color) => ({
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px',
  borderRadius: 999, fontSize: 11, fontWeight: 700, background: bg, color,
  fontFamily: 'var(--font-sans)', whiteSpace: 'nowrap',
});

export function VerifiedBadge({ story, compact }) {
  const n = story.source_count ?? 0;
  if (story.verified) {
    return (
      <span style={badgeStyle('var(--sev-calm-ghost)', 'var(--sev-calm)')} title="Подтверждено независимыми источниками">
        {n} {compact ? '' : 'источник(ов)'}
      </span>
    );
  }
  return (
    <span style={badgeStyle('var(--surface-3)', 'var(--fg-3)')} title="Недостаточно независимых источников">
      ± {n}
    </span>
  );
}

export function CredibilityBadge({ story }) {
  if (story.credibility === 'suspect') {
    return (
      <span style={badgeStyle('var(--sev-critical-ghost)', 'var(--sev-critical-bright)')} title={story.credibility_note || ''}>
        <Icon name="warning" size={11} color="var(--sev-critical-bright)" />
        требует проверки
      </span>
    );
  }
  if (story.credibility === 'credible') {
    return (
      <span style={badgeStyle('var(--sev-calm-ghost)', 'var(--sev-calm)')} title={story.credibility_note || ''}>
        <Icon name="check" size={11} color="var(--sev-calm)" />
        проверено
      </span>
    );
  }
  return null;
}
