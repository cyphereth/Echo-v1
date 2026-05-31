---
name: echo-radar-design
description: Use this skill to generate well-branded interfaces and assets for Echo Radar (репутационный радар для брендов в Instagram и TikTok), either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping. Trigger when designing screens, slides, landing pages, mocks or any visual artifact for Echo Radar.
user-invocable: true
---

# Echo Radar — Design Skill

Read `README.md` in this skill first — it holds the full context: product, content
fundamentals (tone, casing, «вы», no emoji), visual foundations (dark graphite +
cold cyan brand, warm severity signals), iconography, and an index of every file.

Then explore the other files:
- `colors_and_type.css` — all design tokens (colors, type scale, spacing, radii, shadows,
  glows, motion). Include it and add class `echo` to `<body>`; use semantic classes
  (`.echo-h1`, `.echo-eyebrow`, `.echo-metric`) and CSS vars.
- `assets/` — logo (`logo-full-dark.svg`, `logo-mark.svg`). The «Echo )))» wordmark
  broadcasts signal waves from the letter o.
- `preview/` — reference cards for every foundation and component (colors, type, spacing,
  buttons, badges, severity gauge, mention card, platform marks).
- `ui_kits/app/` — the product: dispatch-center inbox (PR/SMM lanes, mention card,
  severity ring, draft editor, probes). Read its `README.md` + `.jsx` components.
- `ui_kits/website/` — the marketing landing.

## Working rules
- **Tone:** спокойная компетентность диспетчера. На «вы», sentence case, без КАПСА
  (кроме mono-лейблов), без восклицаний и эмодзи в хроме. Срочность передаётся
  данными и цветом, не словами. Черновики ответов всегда с конкретным следующим шагом.
- **Color law:** спокойствие — фон (95% экрана), срочность — точка. Тёплый цвет
  (alый «залетает», янтарный «растёт») — дефицитный ресурс, только для high-severity.
  Холодный циан — бренд/«под контролем».
- **Icons:** Lucide (тонкий stroke). Глифы площадок — встроенные SVG (IG/TikTok/X/Telegram).
- **Fonts:** Manrope (UI/заголовки) + JetBrains Mono (данные, метрики, эйброу). С CDN.

## Output
If creating visual artifacts (slides, mocks, throwaway prototypes), copy assets out and
create **self-contained** static HTML for the user to view — inline the tokens from
`colors_and_type.css` and load fonts/React/Babel from CDN (this preview environment does
not serve local sub-resources; the UI kits are built the same way — see their READMEs).
If working on production code, copy assets and read the rules here to become an expert in
designing with this brand.

If invoked without guidance, ask what to build, ask a few focused questions, and act as an
expert designer who outputs HTML artifacts _or_ production code, depending on the need.
