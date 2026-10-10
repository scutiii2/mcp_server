# Emberlings page redesign

> **Renamed 2026-10-11:** the game is now called Ascension and Sparks are Ascended (see `2026-10-11-ascension-rename-design.md`). This record keeps the names it was written with.

Date: 2026-10-11. Scope: `apps/Ember/ember_web` only. No backend change.

## Goal

The Emberlings page gets its own visual identity (palette, type, shapes, tone) instead of the Ember app's. The design comes from ChatGPT's handoff pack, kept as reference in `docs/design/emberlings/`:

- `STYLE-SHEET.md`: palette, fonts, spacing, components, accessibility and motion rules. This is the source of truth for every value below.
- `style.css`: the CSS the mockups were rendered with. A reference for exact values, not code to import: it loads fonts from Google Fonts, which the app's content-security policy blocks.
- `screens.js`: the SVG path data for the icons.
- `ART-PROMPTS.md`: how the Spark artwork sheets were made.

The 56 mockup PNGs (desktop 2560 px wide, phone 780 px wide) stay outside the repository, in the pack at `C:\Users\User\.codex\visualizations\2026\10\10\01a126c6-960e-79a2-992e-6085714a45a7\emberlings\images\` (about 31 MB). Their file names map to the screens: `01` menu, `02` starter pick, `03` collection, `04` find opponent, `05` arena, `06` EMBLEM prompt, `07` results, `08` shop, `09` shared states, `10` to `28` the individual states and dialogs.

## What stays

- The store (`stores/emberlings.ts`), the API client, the battle loop, the idempotency keys and every rule in the page's behavior. Only the look and the markup change.
- The card frame and card back art, the fixed tier colors and the fixed ability-category colors.
- The route, the permission (`emberlings.play`) and Ember's own navigation rail around the page.

## What changes

1. **A scoped theme.** The page root gets a class (`em-root`) that defines the page's CSS custom properties (`--em-*`: colors, radius, spacing, fonts). Nothing leaks to the rest of Ember, and the rest of Ember's tokens are not used inside the page.
2. **Own components.** The Emberlings components stop using Ember's shared `SegmentedControl`, `BaseModal`, `ConfirmModal`, `CountdownRing`, the `chip` and `primary` button classes and `TierBadge`. They get small Emberlings versions under `components/emberlings/ui/`: button, tabs, panel, dialog, confirm dialog, tier badge, stat bar, countdown ring, toast, switch. Ember's shared components stay for the rest of the app.
3. **Fonts.** Silkscreen (headings, short text only) and Inter (everything else), bundled with `@fontsource/silkscreen` and `@fontsource/inter` (both SIL Open Font License), imported by the page only, so the app's `default-src 'self'` policy holds. Latin subsets only.
4. **Icons.** The 12 required icons plus check, coin (Insignia), clock, lock, warning and spark, as one `EmIcon` component over a path table taken from `screens.js`. 24 x 24 grid, 1.8 px stroke, square caps, miter joins, inherit the text color.
5. **Spark artwork.** `starters.png` and `extra-sparks.png` are sliced into six portraits (Guardian, Scout, Striker, Sentinel, Channeler, Forbidden) as WebP files under `src/assets/emberlings/sparks/`. The card's artwork window shows them; a Spark without art (Bruiser) keeps the letter placeholder. The card component takes its art from a small table keyed by Spark id, so adding a Spark's art is one file and one line.
6. **Card tweaks.** The compact card follows the mockup: the frame, the artwork, the name and level in the header, and a tier label plate at the bottom. The large card stays as built (stats, passive, abilities). Text positions stay measured against the frame so the name never overlaps the rivets.
7. **Radius test.** The UI radius is 2 px. It is declared once as `--em-radius: 2px` in the theme and used as `var(--em-radius)`, so `radiusScale.test.ts` (no literal `border-radius` values) keeps passing without an exception list entry.
8. **Copy.** The mockups' page names and taglines are used as designed ("Your Collection", "The Forge Arena", "Collect. Forge. Battle."). The "Design study" footer lines are not.

## Screens

Each screen is built to its desktop and phone mockup (1280 px and 390 px wide).

| Screen | Mockups | Notes |
| --- | --- | --- |
| Main menu | 01, 10 | Menu rows with icon, label and arrow; fanned card hand; wallet in the header |
| Starter pick | 02 | Column of three small cards, the chosen one with the copper outline and a "Selected" label, the large card, the start button |
| Collection | 03, 11 | Small cards with tier, copies, XP or cap line, faint countdown; face-down cards; the Spark dialog with personalities and five presets |
| Find opponent and setup | 04, 12, 13 | Search with cooldown, wild preview, decline or fight, setup form |
| Arena | 05 | Two fighters with HP bars, round log (latest first), action panel with ability buttons |
| EMBLEM prompt | 06, 14 | Five-second ring, permitted tiers, "Let my Spark decide", the time-up state |
| Results | 07, 15 to 20 | One banner per result kind, rewards only when awarded |
| Shop | 08 | Wallet, EMBLEM rows, copies, selling |
| Shared | 09 | Loading, unavailable, reconnecting, errors, reset confirm, How to play, empty states, toast |

## Accessibility

Follow the style sheet: 44 px targets, 2 px copper focus outline with 3 px offset, selection shown by a text label as well as the outline, tier and category always named in text, dialogs trap focus and restore it, progress bars carry values and labels, status messages use live regions, and `prefers-reduced-motion` removes position, particle and width animation. The style sheet's own note applies: card text contrast must be checked against the real tinted frame, not only against a flat sample.

## Risks and decisions

- **Bruiser has no art.** The letter placeholder shows until ChatGPT or an artist supplies a sheet.
- **Mockup data is representative.** Example prices, rewards and the "Ashwarden" Spark are not real; the screens bind to the real store data.
- **Page weight.** Six portraits plus two fonts add about 1.2 MB, precached by the PWA. Acceptable; the portraits are resized to the size the large card needs (2x of 440 px at most).
- **Tier tint is CSS.** The style sheet calls it illustrative. It stays until the art pipeline supplies per-tier frame files.
- **Existing tests change.** Selectors tied to the old markup are updated per step; the behavior tests stay.

## Out of scope

Backend changes, serving card images through the API (see `_TODO.md`), new game rules, sound, and any other Ember page.
