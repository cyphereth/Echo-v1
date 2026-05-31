// ============================================================================
// Echo Radar — Website kit · primitives (PlatformMark)
// ============================================================================
const PF = {
  instagram: { glyph: 'instagram', color: '#E1306C', bg: 'rgba(225,48,108,.14)', label: 'Instagram' },
  tiktok:    { glyph: 'tiktok',    color: '#EAF1F8', bg: '#0A1420',              label: 'TikTok' },
  twitter:   { glyph: 'twitter',   color: '#EAF1F8', bg: '#0A1420',              label: 'Twitter' },
  telegram:  { glyph: 'telegram',  color: '#29A9EB', bg: 'rgba(41,169,235,.14)', label: 'Telegram' },
};
function PlatformMark({ platform, size = 28 }) {
  const p = PF[platform] || PF.instagram;
  return (
    <span style={{ width: size, height: size, borderRadius: 9, background: p.bg, display: 'grid', placeItems: 'center', border: '1px solid var(--line-2)' }}>
      <Icon name={p.glyph} size={size * 0.58} color={p.color} />
    </span>
  );
}
