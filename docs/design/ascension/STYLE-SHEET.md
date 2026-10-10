# Ascension — steel, sparks and small adventures

Design handoff · 11 October 2026

Ascension has its own visual identity: cool forge steel, copper controls, warm ivory text, pixel headings and portrait cards. The existing riveted steel frame and Ascension card back remain the visual anchors. UI panels stay flat and quiet so the cards carry the detail. Language uses **Ascended**, **Insignia** and **EMBLEM** throughout.

## 1. Palette

| Token | Hex | Use |
|---|---|---|
| Background | `#101720` | Page, inset fields, badge surfaces |
| Header | `#141E28` | Masthead, navigation wells |
| Panel | `#1B2733` | Dialogs and content panels |
| Raised panel | `#253443` | Secondary controls, selected segments |
| Primary text | `#F5F0E6` | Headings and body |
| Secondary text | `#B8C6D2` | Captions, help, metadata |
| Control border | `#6B7F90` | Panel and interactive boundaries |
| Divider | `#435463` | Noninteractive separators |
| Copper accent | `#F3B47A` | Primary buttons, links, selection, countdown |
| Text on copper | `#20180F` | Primary button labels |
| Success | `#9AD5AC` | Healthy HP, saved, victory |
| Danger | `#FF9B9B` | Damage, fainted, forfeit, reset, errors |
| Warning | `#F0CC85` | Reconnecting, deadline, escape |
| Danger surface | `#36252E` | Destructive controls and error notices |
| Warning surface | `#302A20` | Countdown and connection notices |
| Disabled text | `#B1BCC8` | Disabled labels stay legible |
| Disabled surface | `#202B36` | Unavailable controls |
| Card text ink | `#14202B` | Text over the existing light steel plates |

These are the six tier hues specified in the brief, with light values chosen for legibility against dark steel:

| Tier | Color | Hex |
|---|---|---|
| Normal | Grey | `#BDC7D0` |
| Rare | Green | `#9AD5AC` |
| Legendary | Blue | `#94C7FF` |
| Royalty | Purple | `#D4B1FF` |
| Ascended | Gold | `#F0CC85` |
| Forbidden | Red | `#FF9B9B` |

| Ability category | Hex |
|---|---|
| Attack | `#FF9B9B` |
| Defense | `#94C7FF` |
| Support | `#9AD5AC` |
| Flee | `#F3B47A` |
| Intercept | `#D4B1FF` |

Tier colors tint only the steel frame, the tier label and its border. Keep artwork untinted. Every tier and category always has its written name. A fainted card is greyed, but its caption also says **Fainted, ready in 1:29**. Locked abilities have an unlock level; cooldowns have a round count. These meanings never rely on color alone.

Calculated WCAG contrast ratios for flat UI surfaces: primary text on the raised surface **11.20:1**; secondary text on the raised surface **7.30:1**; button ink on copper **9.69:1**; danger text on its surface **7.13:1**; disabled text on its surface **7.46:1**. Card ink on a representative `#8C9AAA` steel plate is **5.76:1**. The frame is textured; verify final card text against the actual tier-tinted asset, rather than treating the sampled flat color as a complete textured-asset audit.

## 2. Typography

Use **Silkscreen** for display headings and **Inter** for readable body copy, controls and numbers. Both are free under the SIL Open Font License: [Silkscreen license](https://github.com/google/fonts/blob/main/ofl/silkscreen/OFL.txt), [Inter license](https://github.com/google/fonts/blob/main/ofl/inter/OFL.txt).

| Role | Font | Desktop | Phone | Weight | Line height |
|---|---|---|---|---|---|
| Main menu title | Silkscreen | 46 px | 31 px | 400 | 1.2 |
| Page title | Silkscreen | 28 px | 23 px | 400 | 1.3 |
| Section heading | Silkscreen | 18 px | 18 px | 400 | 1.4 |
| Dialog heading | Silkscreen | 18 px | 17 px | 400 | 1.4 |
| Subheading | Inter | 16 px | 16 px | 700 | 1.5 |
| Body | Inter | 14 px | 14 px | 400 | 1.5 / 21 px |
| Button / selected label | Inter | 14 px | 14 px | 600 | 1.5 |
| Caption / tier / field label | Inter | 12 px | 12 px | 400–600 | 1.5 / 18 px |
| Eyebrow / presentation footer | Inter | 11 px | 11 px | 700 / 400 | 1.5 |
| HP / XP / currency / cooldown | Inter | 12–14 px | 12–14 px | 400–700 | 1.5 |
| Reward amount / timer | Silkscreen | 24 px | 20–24 px | 400 | 1.2 |

Use tabular numbers for currency, XP, HP, levels and countdowns. Pixel typography is reserved for short text. The long copy remains Inter. Eyebrows have 2 px letter spacing. The Ascended name plate uses a bold uppercase Inter label, rather than squeezing a wide pixel font into the art.

Large card text uses a 12 px minimum for stats, passive descriptions and ability metadata on phones; desktop card text scales with the 440 px frame. Small cards intentionally omit detailed stats and ability text. Their outside captions remain 12 px.

## 3. Spacing, shapes and depth

- Base spacing unit: **4 px**. Main reusable tokens: **4, 8, 12, 16, 24, 32, 48 px**. Use 20 and 28 px as derived 4 px increments for control groups and title spacing.
- Desktop content: **1184 px** inside a 1280 px viewport, with **48 px** side gutters. Phone: **16 px** side gutters, leaving **358 px** at 390 px.
- Panel padding: **24 px** desktop, about **16–20 px** phone. Dialog padding: **28 px** desktop, **20 px** phone; card-detail dialogs use **18 px** phone to preserve card width.
- Primary control target: at least **44 × 44 px**. Group gap: **12 px**. Large section gap: **32 px**.
- UI corner radius: **2 px**. Card wrapper: **3 px**. The original card art keeps its stepped corners and rivets. Reward medallions may use an **8 px clipped corner**. The timer is the only circular structural element.
- Control and panel borders: **1 px solid `#6B7F90`**. Dividers: **1 px `#435463`**. Modal top rule: **3 px copper**, or danger for destructive confirmations.
- Panel shadow: `0 5px 0 #090F17`. Dialog shadow: `0 18px 60px #0009`. Primary button has a **3 px** darker copper bottom edge.
- Selected card: **2 px copper outline**, **3 px outline offset**, `0 0 0 6px #F3B47A22` and `0 0 24px #F3B47A33`. Also show **✓ Selected** in text. A persistent glow must not pulse.
- Keyboard focus: **2 px copper outline**, **3 px offset**. Focus must remain distinct from selection.

Keep the cards at the original **1060:1484** portrait ratio. Small cards are **150–180 px**; the menu hand uses three overlapping 170 px cards on desktop and 150 px cards on phone. Detailed cards are **440 px** on desktop and shrink to the available phone width. The desktop starter picker is a column of three cards, a large card and an explanation. The phone version keeps the three-card column and stacks the large card and CTA below it.

## 4. Buttons, tabs and segmented controls

| Style | Background | Label | Border / behavior |
|---|---|---|---|
| Primary | Copper `#F3B47A` | `#20180F` | Copper border; darker bottom edge |
| Secondary | Raised `#253443` | Ivory `#F5F0E6` | Steel border |
| Danger | `#36252E` | `#FF9B9B` | Danger border; explicit verb |
| Disabled | `#202B36` | `#B1BCC8` | `#738391`; no shadow; disabled semantics |
| Ability | Raised | Category hue | Category name in text; power and cooldown below |

On hover, lighten the surface slightly. On press, remove the primary button’s bottom edge and shift by 1 px. Never use a motion effect to indicate whether an action succeeded. Disabled controls say why: **Unlocks at Lv. 10**, **1 round remaining**, or **Search ready in 0:18**. Expensive shop rows display the price, wallet and a shared **not enough Insignia** hint.

Navigation and preset controls sit in a dark bordered well with a **4 px** inset. Selected segments have the raised surface, ivory text and a **2 px copper bottom rule**. Five preset tabs use visible numbers **1–5**. Mode controls always spell out **Manual** and **Autonomous**. Selected tabs need selected semantics in implementation, in addition to the visual rule.

Switches use a squared **40 × 24 px** track and **16 px** thumb. Copper indicates on, slate indicates off. The paired name and tier stay visible; implement a 44 px clickable label region and keyboard operation. Limit each preset to three equipped personalities, with an explicit **2 of 3 equipped** count.

## 5. Icon style

Original geometric SVGs on a **24 × 24** grid. Straight strokes, miter joins, square caps, no gradients, no colored emoji. Standard size **18 px**, stroke **1.8 px**; empty-state and reward icons **40 px**. Use monochrome icons that inherit their text color. Icon-only close buttons have accessible labels and 44 px targets.

Required icons: **play, battle, shop, book, reset, heart, flame, feather, shield, sword, arrow, close**. Supporting icons: **check, coin/Insignia, clock, lock, warning, spark**. `screens.js` contains the exact SVG path definitions used in the mockups. Heart = HP; flame = Essence / EMBLEM; feather = Speed; shield = Defense; sword = Attack. Retain written stat and action names.

## 6. Components and states

**Dialog.** Bordered steel surface, copper top rule, explicit title and close control. Standard width up to **560 px**; card-detail width up to **1030 px**, with 440 px artwork beside the editor. On phone, dialogs fill the safe content width and scroll vertically. Put the close control in the visible title region in production. Trap focus, restore it on close and make the page behind the modal inert. Destructive dialogs use a danger top rule. Reset requires the exact word **RESET**; its destructive button is disabled beforehand. Forfeit uses **Keep battling** and **Forfeit battle**.

**Banners.** Use an icon, explicit status phrase and readable text. Success green for **You won**; danger red for **Your Ascended was knocked out** and **You forfeited**; copper for **Captured**; warning gold for both escape outcomes. Result pages show rewards only when awarded. Zero-reward outcomes say **No rewards from this battle**. Knockout also shows the recovery countdown.

**Connection banner.** Warning surface, clock icon, **Reconnecting… Your battle will resume when connected.** Preserve the existing arena beneath it. Loading uses static card-shaped placeholders and **Loading your Sparks…**. Service failure names the problem and offers **Retry**. Inline errors stay next to the relevant form or purchase context and retain inputs.

**Toast.** Bordered green steel surface, check icon and **Preset 1 saved. Guardian is ready.** Up to **420 px** wide; bottom right desktop, content-width phone. Allow approximately **4 seconds**, pause dismissal while hovered or focused, and keep the saved state represented in the editor. Announce with a polite live region.

**XP and HP.** XP track **6 px** high, copper fill, explicit **40 / 300 XP** label. At cap, replace XP with **Highest level reached**. HP track **12 px**, healthy green; low HP red below 30%, always with **HP 42 / 180**. No color-only information. Use progressbar values and accessible labels in implementation.

**Countdown ring.** **88 px** desktop and **80 px** phone. **6 px** copper track around a dark center; a tabular seconds label remains visible. The active mockup shows **4s** partway through the five-second deadline. At **0s**, use a slate ring, **Time is up**, disabled throw controls and **Your Ascended will decide this turn**. List only permitted tiers with owned counts. A zero-owned tier is disabled. **Let my Ascended decide** stays a clearly separate action while the timer runs.

**Tooltips.** Dark background, 1 px steel border, 12 px ivory copy, **8 × 12 px** padding. Show by focus as well as hover. Include cooldown and ability category; essential explanations also appear inline. On phones, keep cooldown text on the button instead of requiring a tooltip.

**Collection captions.** Each owned card has the tier name, copies, XP or cap label, and recovery countdown if fainted. Unowned cards use the existing flame back plus a written Ascended name and capture/shop hint. The detail dialog includes **Level 7 of 30**, personality tiers, **Show more**, five preset slots, switches and Save.

**Shop.** Wallet always has whole-number Insignia and six labeled EMBLEM counts. Price and Buy stay on the same row at 390 px. Buying copies has Ascended and tier selectors. Selling has an absorbed-copy selector and an explicit return amount. **No absorbed copies to sell** replaces the sale form when empty.

**Responsive arena.** Desktop opponents face each other across a VS marker, followed by the action panel and scrollable log. Phone opponents stack, keeping their names and HP beside their artwork; actions become a two-column grid, and the log follows. Preserve the player/wild labels. In a production screen, make the action area reachable without losing the current HP context, for example with compact HP summaries while the arena scrolls.

## 7. Motion

These are optional implementation ideas; the exported images are static:

| Interaction | Animation | Duration |
|---|---|---|
| Button hover / focus | Surface-color change | 120 ms |
| Card selection | Outline/glow fade-in | 160 ms |
| Dialog opening | Opacity + 4 px rise | 180 ms |
| HP / XP update | Width transition, then settle | 220 ms |
| Successful capture | A few original square ember particles | 350 ms |
| Save toast | Opacity fade | 160 ms |
| Deadline | Ring decreases linearly; numeral updates each second | 5,000 ms total |

With `prefers-reduced-motion: reduce`, remove position, particle and width animations. Change bars directly; update the timer number and ring directly. Keep every status label, action and deadline. No shaking, flashing, auto-scrolling round log or perpetual selected-card pulsing. Countdown expiry is a timed game rule, not an animation dependency.

## Deliverable map and assumptions

`index.html` is the image gallery. `images/01` through `images/09` cover the nine requested screen groups in desktop and phone versions. `images/10` through `images/28` supply the individual secondary states, including each of the six battle results. `mockups.html?screen=menu` is the editable browser source; it is a static design presentation, not a connected game.

Images were rendered at **2×**: **2560 px** wide from a 1280 px desktop viewport and **780 px** wide from a 390 px phone viewport. Phone exports show the complete scrollable page. `manifest.json` records dimensions, font checks and horizontal-overflow checks.

The existing `card_frame.webp` and `card_back.png` were copied from the Ember project. Original illustrative Ascended artwork was generated using the built-in image-generation tool; the prompts are in `ART-PROMPTS.md`. Names for the three starters, their stats, growth and abilities follow the repository catalog. Other example personalities, counts, shop prices, rewards and the uncollected Ashwarden are representative design data rather than a live profile. The tier tint is an illustrative CSS treatment; production should use the art pipeline’s final tier frames. No third-party game characters were used.
