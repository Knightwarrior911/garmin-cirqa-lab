# DESIGN.md

## Theme

Light. Scene: an athlete at a bright kitchen counter in the morning, laptop open,
coffee, checking recovery before training. Light is forced by the scene.

## Color

Page surface `#f7f7f5` (warm-tinted off-white, never #fff). Ink `#1d1d1f`.
Secondary text `#86868b`. Hairlines `rgba(0,0,0,.09)`.

Strategy: Restrained. One accent (Apple blue `#0071e3`) for interactive elements only.
Data colors are semantic and muted:

- good/recovery green `#2f9e5f`
- watch amber `#d9962b`
- rest red `#d64545`
- sleep deep `#3573b9`, REM `#6f9fd8`, light `#b8d49a`, awake `#d98a80`
- body battery `#7fb069`, steps `#7d9bb5`

## Typography

System stack: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI Variable",
"Segoe UI", sans-serif`. One family everywhere. Sentence case; no uppercase microcopy.

Scale (fixed px): hero numeral 64/600/-0.035em · block numeral 40/600/-0.03em ·
section title 15/600 · body 14/400 · label 12/400 `#86868b` · micro 11/400.
Tabular numerals on all data values.

## Layout

Max width 1080px. Section rhythm 56px. Hairline dividers instead of boxes wherever
possible. Hero row is asymmetric: Recovery dominant left, Sleep and Load stacked right,
single vertical hairline between. No nested cards.

## Components

- Segmented control: track `#e8e8ed`, selected pill white with subtle shadow.
- Inputs: white surface, hairline border, blue focus ring.
- Insight rows: hairline-separated list, severity dot, chevron expand.
- Buttons: `#0071e3` primary, radius 8px.

## Motion

150-250ms ease-out. Hover tints, expand transitions, one 180ms page fade.
No orchestrated load sequences.
