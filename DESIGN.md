# Design System — Replay

## Product Context
- **What this is:** A web-based 4D Gaussian Splat viewer. Load a trained 4DGS model, orbit in 3D space, scrub through time.
- **Who it's for:** The build team (Aditya, Divij, Arshia, Mia) for demo and verification. Audience: anyone being demoed to.
- **Space/industry:** 3D/4D reconstruction, computer vision visualization
- **Project type:** Full-viewport web app / scientific visualization tool
- **Design priority:** Demo-quality — first impression matters. The UI sets the emotional tone before the model even loads.

## Aesthetic Direction
- **Direction:** Retro-Futuristic / Scientific Instrument
- **Decoration level:** Intentional — subtle scanline texture on dark surfaces, precise grid lines on loading state
- **Mood:** Feels like a film editing suite crossed with telescope control software. Dark, precise, purposeful. Not generic "AI startup dark mode" — more like precision equipment for seeing things humans couldn't see before.
- **Key insight:** Every existing Gaussian splat viewer treats the UI as secondary to the canvas. In a demo, the first 3 seconds before the model loads set the entire emotional tone. A viewer that looks like precision scientific equipment before the model appears makes the model feel more impressive when it does.

## Typography
- **All UI / Display / Labels:** Geist — clean, engineered feel, excellent tabular-nums support
- **Frame counters / timestamps / technical data:** Geist Mono — monospace signals precision, each digit same width for clean scrubbing
- **Blacklisted:** Inter, Roboto, any system font as primary
- **Loading:** Google Fonts CDN — `https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@300;400;500;600&display=swap`
- **Scale:**
  - Display/Hero: 56–96px, weight 700, tracking −0.03em
  - Frame counter: 36–48px, Geist Mono weight 600, tabular-nums
  - Body: 15px, weight 400, line-height 1.6
  - Labels/UI: 11–13px, weight 500, tracking 0.04–0.08em
  - Technical data (coords, stats): 10–11px Geist Mono, weight 400
  - Micro labels: 9–10px Geist Mono, weight 500, tracking 0.10–0.16em, uppercase

## Color
- **Approach:** Dual-accent — one for spatial (camera/orbit), one for temporal (frame/timeline). This makes the 4D nature of the content legible in the UI itself.

### Palette
```
--bg:              #0A0A0F   /* Near-black with blue undertone — not pure black */
--surface:         #13131A   /* Panels, cards, HUD overlays */
--surface-2:       #1A1A24   /* Slightly lighter surface variant */
--border:          #1E1E2E   /* Dividers, panel edges */
--border-bright:   #2E2E44   /* Focused borders */
--text:            #E8E8F0   /* Cool white — primary text */
--text-muted:      #6B6B7A   /* Secondary text, labels */
--text-dim:        #3A3A4A   /* Placeholder, disabled */

/* Spatial accent — camera, orbit, spatial data */
--accent-cyan:     #00D4FF
--accent-cyan-dim: rgba(0, 212, 255, 0.12)

/* Temporal accent — frame number, timeline, time data */
--accent-orange:   #FF6B35
--accent-orange-dim: rgba(255, 107, 53, 0.12)
```

### Semantic Colors
```
success: #22C55E  (rgba(34,197,94,0.1) background, rgba(34,197,94,0.25) border)
warning: #EAB308  (rgba(234,179,8,0.1) background, rgba(234,179,8,0.25) border)
error:   #EF4444  (rgba(239,68,68,0.1) background, rgba(239,68,68,0.25) border)
info:    --accent-cyan (rgba(0,212,255,0.12) background, rgba(0,212,255,0.25) border)
```

### Dark Mode
This is a dark-only application. The 3D canvas requires a dark background to render correctly. Light mode is supported for surrounding UI pages (marketing, docs) only — reduce saturation by 15–20% and flip surface/background values.

## Spacing
- **Base unit:** 8px
- **Density:** Compact — this is a precision tool, not a landing page
- **Scale:**
  - 2xs: 2px
  - xs: 4px
  - sm: 8px
  - md: 16px
  - lg: 24px
  - xl: 32px
  - 2xl: 48px
  - 3xl: 64px

## Layout
- **Approach:** Full-viewport canvas, HUD overlay pattern
- **Canvas:** 100vw × 100vh, WebGL context, z-index 0
- **Controls:** Float as HUD overlays. No sidebars. No permanent chrome. The scene IS the interface.
- **Time slider:** Docks to bottom center. Spans ~60% of viewport width.
- **Frame counter:** Anchored left of the timeline slider. 36–48px Geist Mono. Big and prominent.
- **Orbit hints:** Bottom-left corner, 9px Geist Mono, fade out after 5s
- **Camera controls:** Top-right corner stack, 28×28px buttons
- **Max content width:** N/A — full viewport
- **Border radius:** sm: 2px (tags, kbd), md: 4px (buttons, inputs, controls), lg: 6px (cards, panels), full: 9999px (dots)

## Motion
- **Approach:** Intentional — only motion that aids comprehension
- **HUD auto-hide:** Controls fade out (opacity 0) after 2s idle on canvas. Fade in on any mouse movement. Duration: 400ms ease-in-out.
- **Loading state:** Progress ring (not a spinner). Ring border-top in --accent-cyan, 1.2s linear rotation. Plus a text progress bar showing exact percentage.
- **Easing:** enter → ease-out, exit → ease-in, move → ease-in-out
- **Duration scale:**
  - Micro: 50–100ms (button hover, icon swap)
  - Short: 150–250ms (tooltip, badge)
  - Medium: 250–400ms (panel fade, controls hide/show)
  - Long: 400–700ms (page transition, modal)
- **No gratuitous animation.** The 3D scene provides all the motion richness. The UI stays still.

## Texture & Decoration
- **Scanline texture:** `repeating-linear-gradient(0deg, transparent 2px, rgba(255,255,255,0.015) 2px, rgba(255,255,255,0.015) 4px)` — fixed overlay, pointer-events none. Subtle. Suggests scientific instrumentation.
- **Grid texture (loading state only):** `linear-gradient` crosshatch at 40px, masked with radial-gradient to center. Gives the loading state a "calibrating" feel.
- **No blobs, no gradients-as-decoration, no purple.**

## Accent Usage Rules
- **Cyan (#00D4FF):** Camera position, orbit indicators, spatial data, interactive controls, focus rings, success-adjacent info states, "load" actions
- **Orange (#FF6B35):** Frame number, timeline scrubber, time-dimension data, playback controls, progress
- **Never mix the two on the same element.** The duality is meaningful — don't dilute it.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-27 | Dual accent system: cyan (spatial) + orange (temporal) | Makes the 4D nature of the content legible in the UI itself. Most viewers use one accent — this differentiates Replay. |
| 2026-03-27 | Oversized frame counter (36–48px Geist Mono) | The time dimension is the product's core feature. Making the frame number big elevates time from afterthought to design element. |
| 2026-03-27 | Scanline texture on dark surfaces | Elevates from "Three.js demo" to "precision scientific tool." Subtle enough to not distract from the scene. |
| 2026-03-27 | Dark-only, full-viewport, no sidebar | Every existing Gaussian splat viewer does this. Table stakes. The scene needs the space. |
| 2026-03-27 | Geist + Geist Mono (not Inter) | Engineered feel, excellent tabular-nums, distinguishes from generic AI tooling. |
| 2026-03-27 | Initial design system created | Created by /design-consultation based on competitive research (Luma AI, Polycam, splat.vercel.app) and first-principles reasoning. |
