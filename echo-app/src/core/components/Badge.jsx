// Shared badge style helper and badge components extracted from Stories.jsx.

export const badgeStyle = (bg, color) => ({
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px',
  borderRadius: 999, fontSize: 11, fontWeight: 700, background: bg, color,
  fontFamily: 'var(--font-sans)', whiteSpace: 'nowrap',
});

export function VerifiedBadge({ story, compact }) {
  const n = story.source_count ?? 0;
  if (story.verified) {
    return (
      <span style={badgeStyle('rgba(34,197,94,0.15)', '#16a34a')} title="Подтверждено независимыми источниками">
        ✓ {n} {compact ? '' : 'источник(ов)'}
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
      <span style={badgeStyle('rgba(239,68,68,0.15)', '#ef4444')} title={story.credibility_note || ''}>
        ⚠ требует проверки
      </span>
    );
  }
  if (story.credibility === 'credible') {
    return (
      <span style={badgeStyle('rgba(34,197,94,0.15)', '#16a34a')} title={story.credibility_note || ''}>
        ✓ проверено
      </span>
    );
  }
  return null;
}
