# Emberlings Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo the user approves each task before it starts and again before it is committed (ember_web workflow), and tests the page by hand: never launch browser-verification agents.

**Goal:** Give the Emberlings page its own palette, type, shapes and components, built from the ChatGPT design pack.

**Architecture:** A scoped theme class (`em-root`) defines `--em-*` custom properties. New small UI components under `components/emberlings/ui/` replace Ember's shared ones inside the page. The store, API client and battle loop stay untouched. Screens are rewritten one task at a time, each ending in a working, tested page.

**Tech Stack:** Vue 3, TypeScript, Pinia, Vitest, `@fontsource/silkscreen`, `@fontsource/inter`.

**Spec:** `docs/superpowers/specs/2026-10-11-emberlings-redesign-design.md`. Design source: `docs/design/emberlings/STYLE-SHEET.md`, `style.css`, `screens.js`; mockup PNGs in the pack named in the spec.

## Global Constraints

- Work in `apps/Ember/ember_web`. No change to `src/stores/emberlings.ts` behavior, `src/api/EmberlingsClient.ts`, or any backend.
- Palette, sizes and rules come from `STYLE-SHEET.md`; copy values from it, never invent new ones. UI corner radius is 2 px, declared only as `--em-radius`.
- No literal `border-radius` values in any `.vue` or `.css` file (`src/radiusScale.test.ts` fails the build). Use `var(--em-radius)` or `var(--radius-*)`.
- Fonts are bundled files only (CSP is `default-src 'self'`): no Google Fonts links, no `@import url(http...)`.
- Spark naming: "Spark", never "creature" or "species". Currency "Insignia", catch item "EMBLEM".
- Every tier and ability category shows its written name; color is never the only signal.
- Primary controls are at least 44 x 44 px; focus outline is 2 px copper with 3 px offset; honor `prefers-reduced-motion`.
- Code is object-oriented where the codebase is; Vue components stay small and single-purpose.
- Tests live beside the component (`*.test.ts`). Run `npx vue-tsc --noEmit` and `npx vitest run` from `apps/Ember/ember_web` before each commit. Commit only on the user's word.
- Do not touch other sessions' uncommitted files (`README.md` hunks about tickets, `e2e/fakeApi.ts`, `api/types.ts`, `CommandFormModal.vue`, `MarkdownContent.vue`, `MessageList.vue`, `ToolRunForm.*`, `utils/toolSchema.ts`, `ChatView.vue`). Stage only your own files; for `README.md` stage only your hunks.

## File structure

New:
- `src/components/emberlings/theme.css`: the `.em-root` tokens, base element styles, focus and motion rules.
- `src/components/emberlings/fonts.ts`: imports the `@fontsource` files.
- `src/components/emberlings/ui/EmIcon.vue`, `EmButton.vue`, `EmTabs.vue`, `EmPanel.vue`, `EmDialog.vue`, `EmConfirm.vue`, `EmTierBadge.vue`, `EmBar.vue`, `EmRing.vue`, `EmSwitch.vue`, `EmToast.vue`, each with a test.
- `src/components/emberlings/ui/icons.ts`: the icon path table.
- `src/components/emberlings/sparkArt.ts`: Spark id to portrait URL.
- `src/assets/emberlings/sparks/<id>.webp`: six portraits.
- `src/components/emberlings/EmShell.vue`: header (logo, tagline, wallet), page title block and the tab navigation.

Rewritten in place (same names, new markup): `MainMenu.vue`, `StarterPick.vue`, `SparkCard.vue`, `SparkTemplateCard.vue` (tweaks only), `CollectionPanel.vue`, `PresetEditor.vue`, `EncounterPanel.vue`, `BattleArena.vue`, `HealthBar.vue`, `RoundLog.vue`, `ActionBar.vue`, `EmblemPrompt.vue`, `BattleResult.vue`, `ShopPanel.vue`, `src/views/EmberlingsView.vue`.

Removed when no longer used: `TierBadge.vue`.

---

### Task 1: Foundation (theme, fonts, icons, UI primitives, shell)

**Files:**
- Create: everything under `ui/`, `theme.css`, `fonts.ts`, `EmShell.vue`
- Modify: `package.json` (two dependencies), `src/views/EmberlingsView.vue` (mount `em-root`, use `EmShell`)
- Test: one `*.test.ts` per new component

**Interfaces:**
- Produces: `EmButton` props `variant: "primary" | "secondary" | "danger"`, `disabled?`, `type?`; `EmTabs` props `modelValue`, `options: { value; label; icon?; disabled? }[]`, `ariaLabel`; `EmDialog` props `open`, `title`, `wide?`, `danger?`, emits `close`, with focus trap and focus restore; `EmConfirm` props `open`, `title`, `message`, `confirmLabel`, `cancelLabel`, `requireText?`, `danger?`, `busy?`, emits `confirm`, `close`; `EmTierBadge` prop `tierId`; `EmBar` props `value`, `max`, `label`, `kind: "xp" | "hp"`; `EmRing` props `remaining`, `total`; `EmSwitch` props `modelValue`, `label`, `disabled?`; `EmToast` props `message`, `open`; `EmIcon` prop `name`, optional `size`.

- [ ] **Step 1:** Install fonts: `npm install @fontsource/silkscreen @fontsource/inter` in `apps/Ember/ember_web`. Import only the Latin 400 and 700 files for Silkscreen and Latin 400, 500, 600, 700 for Inter in `fonts.ts`. Check the built CSS references only local files.
- [ ] **Step 2:** Write `theme.css` from STYLE-SHEET sections 1 to 4 and 7: color tokens, `--em-radius: 2px`, spacing tokens, panel and dialog shadows, focus outline, reduced-motion overrides. Scope everything under `.em-root`.
- [ ] **Step 3:** Write `icons.ts` from `screens.js` (copy the path data, not the markup) and `EmIcon.vue`. Test: every required icon name renders an `svg` with `aria-hidden`.
- [ ] **Step 4:** For each primitive, write the failing test first (keyboard, disabled reason, ARIA roles, emitted events), then the component. `EmDialog` tests: opens and closes, Escape closes, focus moves in and returns to the opener. `EmConfirm` tests: the confirm button stays disabled until the exact `requireText` is typed.
- [ ] **Step 5:** Write `EmShell.vue` (logo with flame icon, tagline "Collect. Forge. Battle.", the Insignia wallet from the store, page title, eyebrow and the `EmTabs` for Collection, Battle and Shop) and switch `EmberlingsView.vue` to it. Keep its existing screen logic.
- [ ] **Step 6:** Run `npx vue-tsc --noEmit`, `npx vitest run`, `npx vite build`; confirm the build output has the two font families as local files and no external URL.
- [ ] **Step 7:** Show the user the shell on the page; commit on approval: `feat(ember-web): Emberlings theme, fonts, icons and UI primitives`.

### Task 2: Spark art and card tweaks

**Files:**
- Create: `src/assets/emberlings/sparks/{guardian,scout,striker,sentinel,channeler,forbidden}.webp`, `sparkArt.ts`, `sparkArt.test.ts`
- Modify: `SparkTemplateCard.vue`, its test

**Interfaces:**
- Produces: `sparkArtUrl(id: string): string | null` (null for a Spark with no art).

- [ ] **Step 1:** Slice each sheet into three equal vertical panels (the sheets are three panels, no gutters), resize each portrait to at most 1060 px wide, save as WebP quality 85. Use a throwaway script in the scratchpad (Pillow in a temporary venv, or the browser canvas); do not add the script to the repo. Check each portrait's size is under 250 KB.
- [ ] **Step 2:** Write `sparkArt.ts` as an explicit id-to-URL table with imports; test known ids resolve and an unknown id returns null.
- [ ] **Step 3:** In `SparkTemplateCard.vue` show the portrait in the artwork window when present (letter placeholder otherwise); compact mode gets the tier label plate at the bottom per mockup 03, replacing the empty ability slots. Update the card tests.
- [ ] **Step 4:** Check the name and level text against the real tinted frame for contrast; adjust positions so nothing overlaps the corner rivets.
- [ ] **Step 5:** `vue-tsc`, tests, commit on approval: `feat(ember-web): Spark portraits and card tweaks`.

### Task 3: Main menu and starter pick

**Files:**
- Modify: `MainMenu.vue`, `StarterPick.vue`, their tests, `e2e/emberlings.spec.ts`

- [ ] **Step 1:** Rebuild `MainMenu.vue` to mockups 01 and 10 using `EmButton`-style rows, `EmIcon`, `EmConfirm` for reset (type `RESET`) and `EmDialog` for How to play. Keep the fanned hand and the no-save and with-save variants. Move the existing behavior tests across.
- [ ] **Step 2:** Rebuild `StarterPick.vue` to mockup 02: three small cards, a "Selected" text label beside the copper outline, the large card, the start button, back link. Keep radio semantics and keyboard picking.
- [ ] **Step 3:** Update the e2e spec selectors; run unit tests and `vue-tsc`.
- [ ] **Step 4:** Commit on approval: `feat(ember-web): redesigned Emberlings menu and starter pick`.

### Task 4: Collection and the Spark dialog

**Files:**
- Modify: `CollectionPanel.vue`, `SparkCard.vue`, `PresetEditor.vue`, their tests

- [ ] **Step 1:** Collection grid and captions to mockup 03: `EmTierBadge`, copies, `EmBar` XP, cap label, faint countdown line, "Not collected yet" face-down cards with hints.
- [ ] **Step 2:** The Spark dialog to mockup 11 with `EmDialog` (wide): large card, level and tier, XP, personalities with "Show more (n)", preset tabs 1 to 5 with `EmTabs`, `EmSwitch` rows with the "2 of 3 equipped" count, Save and the `EmToast` "Preset 1 saved".
- [ ] **Step 3:** Keep every behavior test (paging, three-personality limit, preset load and save); update selectors only.
- [ ] **Step 4:** Commit on approval: `feat(ember-web): redesigned Emberlings collection`.

### Task 5: Battle

**Files:**
- Modify: `EncounterPanel.vue`, `BattleArena.vue`, `HealthBar.vue`, `RoundLog.vue`, `ActionBar.vue`, `EmblemPrompt.vue`, `BattleResult.vue`, their tests

- [ ] **Step 1:** Find-opponent, wild preview and setup (mockups 04, 12, 13): search button with the cooldown reason in text, decline or fight, setup form with `EmTabs` for mode.
- [ ] **Step 2:** Arena to mockup 05: fighters, HP bars with `HP n / m` text and the low-HP red below 30 percent, VS marker, action panel with category-colored ability buttons and the cooldown reason, round log latest first, Forfeit through `EmConfirm`.
- [ ] **Step 3:** EMBLEM prompt to mockups 06 and 14 with `EmRing` and `EmDialog`; time-up state disables the tiers and says "Your Spark will decide this turn". The store's countdown stays the source.
- [ ] **Step 4:** Result banners to mockups 15 to 20: one per result kind, rewards only when awarded, "No rewards from this battle" otherwise, knockout with the recovery countdown.
- [ ] **Step 5:** Phone layout: fighters stack, actions in two columns, compact HP summaries stay reachable.
- [ ] **Step 6:** Keep every store-driven behavior test; commit on approval: `feat(ember-web): redesigned Emberlings battle`.

### Task 6: Shop

**Files:**
- Modify: `ShopPanel.vue`, its test

- [ ] **Step 1:** Rebuild to mockup 08: wallet with Insignia and six EMBLEM counts, price and Buy on one row at 390 px, copies form, sell form with the return amount, the empty state "No absorbed copies to sell", the "not enough Insignia" hint.
- [ ] **Step 2:** Keep purchase and sale behavior tests; commit on approval: `feat(ember-web): redesigned Emberlings shop`.

### Task 7: Shared states, accessibility pass and docs

**Files:**
- Modify: `EmberlingsView.vue`, the page's remaining components, `README.md` (only my hunks), the Brain vault note `Projects/ember_web.md`
- Delete: `TierBadge.vue` and its test, once nothing imports it

- [ ] **Step 1:** Loading placeholders ("Loading your Sparks…"), the unavailable panel with Retry, the reconnecting banner, inline errors (mockup 09).
- [ ] **Step 2:** Accessibility pass against the spec: tab order, focus return, live regions, reduced motion, 44 px targets, written tier and category names. Fix anything that fails.
- [ ] **Step 3:** Run the full suite and `vite build`; update the README and the vault note.
- [ ] **Step 4:** Commit on approval: `docs: Emberlings redesign notes`, plus any fixes.

## Self-review

- **Spec coverage:** theme (Task 1), fonts (1), icons (1), own components (1), Spark art and card tweaks (2), radius test (Global Constraints and 1), all screens (3 to 7), accessibility (1 and 7), out-of-scope items untouched.
- **Open item:** Bruiser has no art; it stays a letter placeholder until a sheet exists.
- **Type consistency:** the `Em*` component props above are the only names later tasks use.
