# Ember component patterns

Copy-ready CSS for the recurring pieces. All values are tokens from [tokens.css](tokens.css). Working Vue versions live in `apps/Ember/ember_web/src/components/` (named per pattern).

## Buttons

```css
/* Primary: accent-filled pill. */
.primary {
  padding: 6px 16px; border: none; border-radius: var(--radius-full);
  cursor: pointer; font-weight: 600;
  color: var(--accent-contrast); background: var(--accent);
}
/* Secondary: outlined pill. */
.secondary {
  padding: 6px 16px; border: 1px solid var(--border); border-radius: var(--radius-full);
  cursor: pointer; color: var(--text); background: transparent;
}
/* Danger: red outline, red text. */
.danger {
  padding: 3px 12px; border: 1px solid var(--danger); border-radius: var(--radius-full);
  cursor: pointer; font-size: 0.85em; color: var(--danger); background: transparent;
}
button:disabled { cursor: default; opacity: 0.5; }
```

Card-style action button (`SaveButton.vue`): `--radius-md`, `1px solid --border`, `--surface` fill, `box-shadow: 0 1px 4px rgba(0,0,0,.15)`; toggled state inverts to `--text` on `--bg`.

`DeleteButton.vue`: red pill with bin icon; while `busy` the label letters fall into the bin, the button shrinks to a circle and a ring spins. Pattern to reuse: a busy state shown on the control itself, with a reduced-motion fallback.

## Input

```css
input, select, textarea {
  padding: 6px 10px; border: 1px solid var(--border);
  border-radius: var(--radius-md); background: var(--bg); color: var(--text);
}
input:focus { outline: none; border-color: var(--accent); }
```

## Card, chip, badge

```css
.card { padding: 12px 14px; margin-bottom: 12px; border: 1px solid var(--border);
        border-radius: var(--radius-lg); background: var(--surface); }
.chip { padding: 2px 10px; border-radius: var(--radius-full); font-size: 0.85em; background: var(--code-bg); }
.badge { padding: 1px 8px; border: 1px solid var(--border); border-radius: var(--radius-full);
         font-size: 0.75em; color: var(--muted); }
.badge.warn { color: var(--danger); border-color: var(--danger); }
```

## Danger zone

Destructive actions in their own block, last in the form.

```css
.danger-zone {
  display: flex; flex-direction: column; align-items: flex-start; gap: 6px;
  margin-top: 16px; padding: 12px;
  border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--danger) 6%, var(--bg));
}
.danger-zone h4 { margin: 0; color: var(--danger); }
```

## Toggle switch (`ToggleSwitch.vue`)

Real `<input type="checkbox" role="switch">` visually hidden (1px, opacity 0), followed by a `.track`. Track 52x24 (small 32x18), `--radius-full`, `color-mix(in srgb, var(--muted) 35%, var(--surface))`; checked: `--accent`. Knob white, diameter `h - 6px`, 3px inset, slides `w - h` px, `0.15s`. Full size shows ON / OFF text inside the track (0.62em, 700); small drops the text. Focus ring on the track via `.input:focus-visible + .track`. Disabled: `opacity .6`.

## Segmented control (`SegmentedControl.vue`)

Accent-filled pill track (`padding: 3px`), one equal-width button per option (`grid-auto-columns: 1fr`), a white thumb that slides by `translateX(calc(var(--i) * 100%))` over `0.18s`. Active label turns `--accent`; others stay white. Plain buttons with `aria-pressed` inside `role="group"`. Use for 2-5 mutually exclusive choices (period, tab).

## Modal (`BaseModal.vue`)

Native `<dialog>` + `showModal()`: `width: min(560px, calc(100vw - 32px))`, `max-height: calc(100vh - 64px)`, `padding: 18px 20px 20px`, `1px solid --border`, `--radius-xl`, `--surface`, backdrop `rgb(0 0 0 / 45%)`. Header: title `h3` 1em plus a muted `×` button. Closes on Escape, ×, and backdrop click by asking the parent (`close` event), never hiding itself.

## Confirm modal (`admin/ConfirmModal.vue`)

Props: `title`, `message`, `confirmLabel`, `danger`, `busy`, `requireText`. Actions right-aligned: outlined Cancel, then Confirm (accent pill, or the red delete button when `danger`). With `requireText`, show "Type `<phrase>` to confirm", an autofocused input with a `typed/length` counter in `--mono`, and keep Confirm disabled until the text matches exactly; Enter confirms when matched.

## Setting row (`SettingRow.vue`)

Flex row, `flex-wrap`, label and description left (`flex: 1 1 220px`), control right, `border-top: 1px solid var(--border)` between rows. Label 500 weight; description 0.85em `--muted`. A setting that differs from its default shows an 8px accent dot before the label (plus a screen-reader "(changed from the default)") and a 28px round reset button after the control (icon only, `aria-label="Reset X to its default"`).

## Icon rail (`NavRail.vue`)

- Column 52px wide, `--surface`, `border-right: 1px solid --border`, `z-index: 30` so tooltips overlap the page. Top: 32px accent wordmark tile (`--radius-md`). Then page icons; bottom group (`margin-top: auto`): theme, account avatar, log out.
- Every rail control is one 36px `--radius-md` square, `--muted` icon; hover and active: `--text` on `--bg`. Active page adds `box-shadow: inset 2px 0 0 var(--accent)`.
- Name tooltip via `[data-label]:hover::after` / `:focus-visible::after`: `left: calc(100% + 8px)`, `--surface`, `1px solid --border`, `--radius-md`, small shadow.
- Status alert (issues): same square, `--tone` is `--warning` or `--status-failed`, with a 16px count badge top-right.
- `max-width: 767px`: the rail becomes a row, `width: 100%; height: var(--rail-height); border-top` instead of right border, active marker `inset 0 -2px 0 var(--accent)`, tooltips hidden, page icons scroll horizontally.

## Tile (`IconTile.vue`)

Centered column card, `--radius-lg`, `--surface`, soft shadow, lifts 2px on hover/focus. Above the label: a soft accent blob (`color-mix(in srgb, var(--accent) 16%, transparent)`) with outlined bubbles and a 40px stroked icon in `--accent`. Label 0.9em/500; optional `--mono` subtitle in `--muted`.

## Tables and code (info pages)

`th`: weight 600, `--muted`; cells `8px 10px`, `border-bottom: 1px solid --border`; table 0.9em; wide tables scroll sideways inside `.table-wrap { overflow-x: auto }`. `pre`: `--bg` fill, `--radius-md`, `--mono` 0.85em, `max-height: 320px`, wraps with `overflow-wrap: anywhere`.

## Page shell

```css
.page { flex: 1; min-height: 0; overflow-y: auto; }
.page .column { max-width: 980px; margin: 0 auto; padding: 24px 16px; }
.page h2 { margin: 0 0 6px; font-size: 1.2em; }
.page .intro { margin: 0 0 16px; font-size: 0.9em; color: var(--muted); }
```
