# Design: LankabelTV

The locked system. Every Hallmark run reads this first and pages share it. Change it on purpose; the file is the rule.

## System
- Genre: atmospheric
- Shape of the first page: app screen
- Theme: brand (LankabelTV), source `src/aniworld/web/static/img/logo.png`
- Axes: dark/grotesk-sans/warm · posture: restrained

## Tokens
`tokens.css` is the source of truth. The roles:
```css
:root {
  --color-paper: oklch(13% 0.035 264);  --color-paper-2: oklch(18% 0.04 264);  --color-paper-3: oklch(23% 0.042 264);
  --color-ink: oklch(95% 0.012 250);  --color-ink-2: oklch(85% 0.018 250);  --color-muted: oklch(70% 0.022 256);  --color-rule: oklch(29% 0.038 264);
  --color-accent: oklch(57.25% 0.217 25.3);  --color-accent-ink: oklch(98% 0.006 80);  --color-focus: oklch(72% 0.18 25.3);
  --font-display: "Rethink Sans", ui-sans-serif, system-ui, sans-serif;  --font-body: var(--font-display);  --font-outlier: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  --radius-card: 0px;  --radius-pill: 2px;  --rule-hair: 1px;  --shadow-card: none;
}
```
Light mode re-derives the same roles under `:root[data-theme="light"]`. The spacing scale, the type scale, the easings and the durations are the scaffold's and live in `tokens.css`.

## Controls
- Primary: brand red fill · 2px radius · 40px visual height, 44px hit target
- Secondary: 1px rule outline or typographic · same radius and height

## Motion
- Character: calm; no page-load reveal, no ambience, no width animation. State changes use colour, opacity or transform only. Under reduced motion everything ends at once.

## Exports
`tokens.css` in this project. Tailwind, DTCG or shadcn blocks are added here on request, per `export-formats.md`.
