---
name: ember-design-system
description: Use when building or restyling any UI (web app, dashboard, admin page, tool front end, mobile or desktop shell) that should look and behave like the ember app - ember orange accent, light-dark theme tokens, one radius scale, icon rail, pill controls. Also use when adding screens to ember_web, or reviewing a UI for visual or interaction consistency with ember.
---

# Ember design system

The look and interaction rules of ember_web, extracted so a new UI feels like the same product. Source of truth in code: `apps/Ember/ember_web/src/style.css` (tokens) and `apps/Ember/ember_web/src/components/`. Framework-agnostic: the examples are Vue, the rules are CSS and behavior.

**Core idea:** one coherent system, not per-component choices. Pick tokens and patterns first, write styles second. Never hardcode a colour or a pixel radius.

## Start a new UI

1. Copy [tokens.css](tokens.css) into the new project's global stylesheet (or import it). It holds every colour, font, radius and the `--rail-height` token, plus the base reset and app-shell rules.
2. Add theme switching (section "Theme" below).
3. Build from the patterns in [components.md](components.md): copy the CSS, keep the tokens.
4. Check against the rules and checklist below.

If the new UI is ember_web itself, reuse the existing components instead (`ember-feature-scaffold` lists them).

## Foundations

**Colour** - every token is `light-dark(light, dark)`, so one declaration themes both. Roles:

| Token | Use |
|---|---|
| `--bg` / `--surface` | page / cards, panels, rail, modals (one step above bg) |
| `--text` / `--muted` | body / secondary text, icons, descriptions |
| `--border` | every 1px outline and divider |
| `--accent` (ember orange `#e8590c` / `#ff7a33`) + `--accent-contrast` | primary action, active state, focus ring, links |
| `--danger`, `--warning`, `--success` | destructive, caution, positive; status red is `--status-failed` |
| `--code-bg` | code, chips, inline tags |

Rules: tinted fills use `color-mix(in srgb, var(--x) N%, var(--bg))`, never a new hex. Colour is never the only cue: pair a status colour with an icon and a label. Chart series colours are categorical slots, validated on both surfaces (see the `dataviz` skill).

**Type** - `--sans` system stack at `15px/1.55`; `--mono` for ids, paths, code. Scale by `em` relative to the parent: body 1em, secondary 0.9em, meta 0.85em, badges 0.75em. Headings are modest: page `h2` 1.2em, section `h3` 1em, weight 600.

**Radius** - pick by element size, never a literal px:

| Token | px | Elements |
|---|---|---|
| `--radius-sm` | 4 | chip, badge, small tag |
| `--radius-md` | 8 | input, row, icon button, tooltip |
| `--radius-lg` | 12 | card, panel, danger zone |
| `--radius-xl` | 16 | modal, sheet |
| `--radius-full` | 9999 | single-line pill button, avatar, toggle, dot only |

A nested corner is `calc(outer - padding)`. An element flush to an edge is square on that side. Only 10-11px chart marks keep a literal `2px`.

**Layout** - the page never scrolls (`body { overflow: hidden }`); each view scrolls its own area (`flex: 1; min-height: 0; overflow-y: auto`). Content column centred, `max-width` 820px (forms) to 980px (info pages), `padding: 24px 16px`. Navigation is a 52px icon rail on the left; below 768px it becomes a bottom bar of height `--rail-height`. Breakpoints used: 767/768 (rail flips). Test at desktop, 768 and 375.

**Surfaces** - cards: `1px solid --border`, `--radius-lg`, `--surface`, `12px 14px` padding. Raised tiles use a soft shadow (`0 2px 10px rgba(0,0,0,.14)`, lifting 2px on hover). No heavy shadows elsewhere; modals use a `rgb(0 0 0 / 45%)` backdrop.

**Motion** - 0.15s ease for hover and state, 0.18s for sliding thumbs; always honour `prefers-reduced-motion: reduce` (drop transitions or slow loops). Animation follows state; it never delays or replaces the action.

**Focus** - `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }` on every interactive element. Never `outline: none` without a replacement.

## Interaction rules

- **Controls:** primary action = accent-filled pill (`--radius-full`, weight 600, `--accent-contrast` text). Secondary = outlined pill. Inputs = `--radius-md`, `--border`, `--bg` fill, accent border on focus. On/off = `ToggleSwitch` pill (real checkbox, `role="switch"`), never a bare checkbox. A handful of exclusive choices = segmented pill (accent track, white sliding thumb). Both in [components.md](components.md).
- **Confirmations:** never the browser's `confirm()`. Use an in-app modal; friction scales with severity. Severe actions (delete account, delete something in use, delete all) require typing the name or phrase (`requireText`) before the confirm button enables. Destructive buttons are red-outlined pills and sit in a red-tinted **Danger zone** block, last in the form.
- **Settings:** a setting that only touches this browser applies instantly and says "Applies instantly. Saved on this device." A setting that reaches other accounts or the server is a draft with an unsaved bar until Save. A setting that differs from its default shows an accent dot and its own reset button; no reset-all.
- **Busy state:** disable the control, set `aria-busy`, show progress on the control itself (spinner ring); ignore clicks while busy.
- **Icons:** stroked 24x24 SVG path data, `stroke: currentColor; stroke-width: 1.8; fill: none; round caps and joins`. Icon-only controls get a name on hover and keyboard focus (`data-label` tooltip) and an `aria-label`.
- **Bottom sheets** sit above the mobile nav bar: `bottom: var(--rail-height)`, not `0`.
- **Persistence:** theme and local preferences in `localStorage`, every read and write in try/catch (storage may be blocked); a failed read means the default.

## Theme

`color-scheme: light dark` on `:root` follows the system. A user override sets `document.documentElement.style.colorScheme` to `light` or `dark`; "system" restores `light dark`. The toggle cycles system, light, dark and persists the choice per browser. Because every token is `light-dark()`, no per-theme stylesheet exists. Apply the saved theme before the app mounts to avoid a flash. See `apps/Ember/ember_web/src/composables/useTheme.ts`.

## Review checklist

- [ ] No hex colour or literal radius outside `tokens.css`
- [ ] Looks right in light, dark, and forced-colour scheme override
- [ ] Desktop, 768 and 375 widths; no horizontal page scroll
- [ ] Every interactive element has a visible focus ring and a name
- [ ] Status shown by icon and text, not colour alone
- [ ] Destructive action: modal, red Danger zone, type-to-confirm if severe
- [ ] Motion respects `prefers-reduced-motion`
- [ ] Scoped component CSS that a parent page also styles uses a more specific selector (`button.delete-button`, not `.delete-button`): a later same-specificity rule had overridden its padding

## Common mistakes

| Mistake | Fix |
|---|---|
| `border-radius: 10px` | Use the nearest token by element size |
| Separate dark-mode stylesheet or `.dark` class | Use `light-dark()` tokens |
| Native `confirm()` or `alert()` | In-app confirm modal |
| Page-level scroll, sticky headers fighting it | Scroll the view area only |
| New accent shade for hover | `color-mix` from `--accent` or change border to accent |
| Fixed bottom sheet at `bottom: 0` on mobile | `bottom: var(--rail-height)` |
