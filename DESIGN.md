# Design System

## Direction

Industrial Data. A local evidence console inspired by chain-of-custody records and editorial contact sheets, not a consumer dashboard.

## Scene

A Windows user on a large monitor has just lost sight of a long-running task and needs to distinguish a real recovery from a reassuring-looking false positive.

## Color

- Canvas: `oklch(0.16 0.008 70)`
- Raised surface: `oklch(0.205 0.01 70)`
- Ledger surface: `oklch(0.235 0.012 70)`
- Primary text: `oklch(0.91 0.018 85)`
- Muted text: `oklch(0.69 0.018 75)`
- Primary accent: `oklch(0.91 0.006 85)`
- Success: `oklch(0.72 0.12 145)`
- Archived: `oklch(0.58 0.01 75)`
- Destructive: `oklch(0.73 0.01 75)`

Use black, white, and graphite grey throughout. Reserve green exclusively for Active state. Never use gradients.

## Typography

- Interface: `Bahnschrift`, `Aptos`, `Trebuchet MS`, sans-serif
- Evidence and identifiers: `Cascadia Mono`, `Consolas`, monospace
- Dense, fixed product scale from 0.75rem to 1.65rem
- Prose width capped at 70ch

## Layout

- 15rem command rail on wide screens
- Status strip across the top of the ledger
- Project-grouped task rows with title, evidence path, source, timestamps, and state
- Collapse to one column below 820px; controls become a horizontal wrap
- Avoid nested cards; use rules, rows, and surface shifts

## Components

- Rectangular controls with 2px corners, never pills
- Full-border white focus treatment
- Buttons have default, hover, active, disabled, and loading states
- Dialogs are reserved for confirmation and help because both interrupt high-risk work
- Toasts report exact outcomes and never substitute for verification

## Motion

- No list-entry or page-load animation
- 140ms transform feedback on button press
- 180ms opacity/transform transition for occasional dialogs and toasts
- Animate only transform and opacity
- Remove transforms under `prefers-reduced-motion: reduce`
