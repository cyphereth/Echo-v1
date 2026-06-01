export function EchoWordmark({ size = 22, color = '#EAF1F8' }) {
  const f = size;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', fontFamily: 'var(--font-sans)' }}>
      <span style={{ fontWeight: 800, fontSize: f, letterSpacing: '-0.04em', color }}>Ech</span>
      <svg width={f * 1.35} height={f * 1.22} viewBox="0 0 62 56"
        style={{ marginLeft: -f * 0.04, alignSelf: 'center', marginBottom: -f * 0.19 }}>
        <defs>
          <radialGradient id="wm-blip" cx="0.5" cy="0.5" r="0.5">
            <stop stopColor="#FF7A87" /><stop offset="1" stopColor="#FF4D5E" />
          </radialGradient>
        </defs>
        <path d="M16 17 A10 10 0 0 0 16 37" stroke={color} strokeWidth="6.6" strokeLinecap="round" fill="none" />
        <path d="M16 17 A10 10 0 0 1 16 37" stroke="#57D2E2" strokeWidth="6.6" strokeLinecap="round" fill="none" />
        <path d="M16 9 A18 18 0 0 1 16 45" stroke="#2BB3C7" strokeOpacity="0.55" strokeWidth="3.4" strokeLinecap="round" fill="none" />
        <path d="M16 2 A25 25 0 0 1 16 52" stroke="#2BB3C7" strokeOpacity="0.30" strokeWidth="3.4" strokeLinecap="round" fill="none" />
        <circle cx="29" cy="14" r="2.7" fill="url(#wm-blip)" />
      </svg>
    </span>
  );
}
