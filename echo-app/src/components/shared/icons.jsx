const PATHS = {
  inbox:        "M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z",
  radio:        "M4.9 19.1C1 15.2 1 8.8 4.9 4.9M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5M12 12h.01M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5M19.1 4.9C23 8.8 23 15.2 19.1 19.1",
  bar3:         "M4 6h16M4 12h16M4 18h16",
  search:       "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
  bell:         "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
  check:        "M5 13l4 4L19 7",
  checkCircle:  "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z",
  x:            "M6 18L18 6M6 6l12 12",
  xCircle:      "M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z",
  edit:         "M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z",
  send:         "M12 19l9 2-9-18-9 18 9-2zm0 0v-8",
  chevronDown:  "M19 9l-7 7-7-7",
  chevronRight: "M9 18l6-6-6-6",
  chevronLeft:  "M15 18l-6-6 6-6",
  arrowLeft:    "M10 19l-7-7m0 0l7-7m-7 7h18",
  externalLink: "M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14",
  eye:          "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 9a3 3 0 100 6 3 3 0 000-6z",
  flame:        "M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z",
  activity:     "M22 12h-4l-3 9L9 3l-3 9H2",
  trendingUp:   "M23 6l-9.5 9.5-5-5L1 18M17 6h6v6",
  messageCircle:"M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
  settings:     "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
  building:     "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4",
  users:        "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
  heart:        "M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z",
  plus:         "M12 4v16m8-8H4",
  filter:       "M3 4h18M7 8h10M10 12h4M12 16h0",
  clock:        "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  zap:          "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  sparkles:     "M12 3v1M12 20v1M4.22 4.22l.707.707M18.364 18.364l.707.707M1 12h1M21 12h1M4.22 19.78l.707-.707M18.364 5.636l.707-.707M12 8a4 4 0 100 8 4 4 0 000-8z",
  pieChart:     "M21.21 15.89A10 10 0 118 2.83M22 12A10 10 0 0012 2v10z",
};

const FILL_ICONS = {
  instagram: (
    <svg viewBox="0 0 24 24" fill="none">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#E1306C"/>
      <circle cx="12" cy="12" r="4" stroke="white" strokeWidth="1.8" fill="none"/>
      <circle cx="17.5" cy="6.5" r="1.2" fill="white"/>
    </svg>
  ),
  tiktok: (
    <svg viewBox="0 0 24 24" fill="none">
      <rect width="24" height="24" rx="5" fill="#1a1a1a"/>
      <path d="M17 8.5c-1.2-.8-2-2-2.2-3.5H12v10.5a2.3 2.3 0 01-2.3 2 2.3 2.3 0 01-2.3-2.3 2.3 2.3 0 012.3-2.3c.2 0 .4 0 .6.1V10c-.2 0-.4-.1-.6-.1a5 5 0 00-5 5 5 5 0 005 5 5 5 0 005-5V9.2c.9.6 1.9 1 3 1.1V7.5c-.5 0-1-.2-1.7-1z" fill="white"/>
    </svg>
  ),
  telegram: (
    <svg viewBox="0 0 24 24" fill="none">
      <rect width="24" height="24" rx="5" fill="#29B6F6"/>
      <path d="M19.2 5.3L4.8 10.8c-.9.4-.9 1.6.1 1.9l3.5 1.1 1.3 4c.2.6 1 .8 1.4.3l1.9-1.9 3.7 2.7c.5.4 1.3.1 1.5-.5l2.6-11.7c.2-1-.7-1.8-1.6-1.4z" fill="white"/>
    </svg>
  ),
};

export function Icon({ name, size = 16, color = 'currentColor', style, strokeWidth = 1.7 }) {
  if (FILL_ICONS[name]) {
    return (
      <span style={{ display: 'inline-flex', width: size, height: size, flexShrink: 0, ...style }}>
        {FILL_ICONS[name]}
      </span>
    );
  }
  const d = PATHS[name];
  if (!d) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0, ...style }}>
      {d.split('M').filter(Boolean).map((seg, i) => (
        <path key={i} d={'M' + seg} />
      ))}
    </svg>
  );
}
