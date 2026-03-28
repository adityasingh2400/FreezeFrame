# Design System — Replay

## Product Context
- **What this is:** A web-based bullet-time / 4D viewer. Pick a moment, orbit it from any angle.
- **Who it's for:** Demo audience (hackathon judges, investors), then end users (athletes, creators, coaches).
- **Design priority:** Premium and sleek — first impression sells the product before the 3D even loads.

## Aesthetic Direction
- **Direction:** Warm Premium — inspired by ReRoute's design system
- **Mood:** Feels like a luxury sports product. Warm, confident, polished. Not cold techno-dark or generic "AI startup." Think high-end film tools meets sports broadcast.
- **Key principle:** The viewer stays dark (content needs it), but every UI element is warm — maroon/rose, cream/amber, generous radius, soft glows. The about/marketing page is full light cream like ReRoute.

## Typography
- **UI text:** DM Sans — clean, warm, premium
- **Display / headings / logo:** Outfit — bold, modern, confident
- **Monospace / data / labels:** JetBrains Mono — precision, excellent tabular-nums
- **Blacklisted:** Inter, Roboto, Geist, any system font as primary
- **Loading:** Google Fonts CDN — `DM+Sans`, `Outfit`, `JetBrains+Mono`
- **Scale:**
  - Display/Logo: 15px Outfit weight 700, tracking 0.14em
  - Frame counter: 36px JetBrains Mono weight 600, tabular-nums
  - Body: 12-14px DM Sans weight 400-500
  - Labels/UI: 10-12px DM Sans or JetBrains Mono, weight 500
  - Micro labels: 8-9px JetBrains Mono, weight 500, tracking 0.08-0.12em, uppercase

## Color

### Viewer (Dark Warm)
```
--bg:              #0D0809   /* Warm near-black, maroon undertone */
--surface:         #171112   /* Warm dark panel */
--surface-2:       #1F1618   /* Slightly lighter */
--border:          #2A1E20   /* Warm border */
--border-bright:   #3E2E32   /* Focused border */
--text:            #FAF6F1   /* Cream white (from ReRoute) */
--text-muted:      #9A8575   /* Warm brown secondary */
--text-dim:        #5A4840   /* Warm dim */

/* Spatial accent — warm rose (camera, orbit, focus) */
--cyan:            #D44060
--cyan-dim:        rgba(212, 64, 96, 0.15)

/* Temporal accent — warm amber (frame, timeline, playback) */
--orange:          #D4956A
--orange-dim:      rgba(212, 149, 106, 0.15)
```

### Marketing/About (Light — direct ReRoute)
```
--bg:              #FAF6F1   /* Cream base */
--surface:         #FFFFFF   /* White cards */
--border:          #E0D3C4   /* Warm border */
--text:            #2A0A10   /* Dark */
--text-secondary:  #6B4A3A   /* Brown muted */
--primary:         #7A1B2D   /* Maroon */
--primary-light:   #9A3040   /* Lighter maroon */
--primary-dim:     #F5E6EA   /* Light maroon background */
```

### Semantic Colors
```
success: #7BA05B  (ReRoute green)
error:   #C41E3A  (ReRoute red)
```

## Spacing
- **Base unit:** 8px
- **Scale:** 4, 8, 16, 24, 32px

## Border Radius
- sm: 6px (buttons, inputs, small pills)
- md: 10px (cards, panels, play button)
- lg: 16px (chat panels, modals)
- full: 100px (badges, speed pills)

## Shadows (warm, soft)
- sm: `0 1px 3px rgba(13, 8, 9, 0.4)`
- md: `0 4px 12px rgba(13, 8, 9, 0.5)`
- lg: `0 8px 32px rgba(13, 8, 9, 0.6)`
- glow-rose: `0 0 12px rgba(212, 64, 96, 0.2)`
- glow-amber: `0 0 12px rgba(212, 149, 106, 0.2)`

## Motion
- Hover lift: `translateY(-1px)` on interactive elements
- Hover glow: box-shadow glow on active/focused state
- Transitions: `all 0.2s ease` (standard), `0.15s` (micro), `0.4s` (panel fade)
- Loading ring: border-top spin, 1.2s linear
- No gratuitous animation. The 3D/image content provides visual richness.

## Accent Usage Rules
- **Rose (#D44060):** Camera position, orbit indicators, spatial data, interactive controls, focus rings, logo, moment labels
- **Amber (#D4956A):** Frame number, timeline scrubber, time-dimension data, playback controls, progress, director mode
- **Maroon (#7A1B2D):** Marketing/light pages only — primary accent, buttons, headings
- Gradient fill on angle indicator: rose → amber (spatial → temporal)

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-28 | Adopt ReRoute warm aesthetic | User directive — ReRoute's design is proven premium. Warm palette differentiates from every other cold dark viewer. |
| 2026-03-28 | DM Sans + Outfit + JetBrains Mono | ReRoute's font stack. DM Sans for body, Outfit for display, JetBrains Mono for data. |
| 2026-03-28 | Generous radius (6/10/16px) | ReRoute uses 6-20px radius. Rounder = warmer, more premium. |
| 2026-03-28 | Rose (#D44060) + Amber (#D4956A) dual accent | Maintains spatial/temporal duality from original design, but in warm ReRoute palette. |
| 2026-03-28 | Light theme for about.html | Marketing page uses ReRoute's exact cream/maroon palette. Viewer stays dark for content. |
| 2026-03-27 | Oversized frame counter (36px) | Retained — the time dimension is the product's core feature. |
| 2026-03-27 | Dark-only viewer, full-viewport, no sidebar | Retained — the scene needs the space. |
