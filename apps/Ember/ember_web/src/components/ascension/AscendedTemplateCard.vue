<script setup lang="ts">
import { computed } from "vue";
import type { AscendedInfo } from "../../api/AscensionClient";
import frameUrl from "../../assets/ascension/card_frame.webp";
import { abilityEffect, passiveText, titleCase } from "../../utils/ascension";
import { ascendedArt } from "./ascendedArt";

/** An Ascended's card, drawn on the card frame (assets/ascension/card_frame.webp,
 * the text-free front template, 1060 x 1484). The frame is the whole
 * background; text and slots sit over it at the template's own positions, given
 * in frame pixels and turned into percentages, so the card scales with its
 * width. The frame's see-through holes show the artwork box and, for each
 * ability, a colour for its category. The frame's metal is tinted for the
 * Ascended's tier; the Ascension plate keeps its own colours. The Ascended's portrait
 * (ascendedArt.ts) shows in the artwork window, or its first letter when it has none.
 * `compact` is the small version for lists: the frame cropped to its top part so the
 * artwork is larger, the name, and a plate with the tier's name at the bottom, no stats
 * or text; `showLevel` adds the level to its header. The width is `--card-width` (440 px,
 * or 150 px compact). */
const props = withDefaults(defineProps<{ ascended: AscendedInfo; level?: number; tierId?: string; compact?: boolean; showLevel?: boolean }>(), {
  level: 1,
  tierId: "common",
  compact: false,
  showLevel: false,
});

const FRAME_W = 1060;
const FRAME_H = 1484;

/** The compact card draws the frame this much taller than the card and shows its top. */
const COMPACT_ZOOM = 1.9;

/** A box in frame pixels as CSS percentages of the card; `zoom` for the cropped compact frame. */
function box(x0: number, y0: number, x1: number, y1: number, zoom = 1): Record<string, string> {
  const pct = (v: number, of: number) => `${(v / of) * 100}%`;
  return { left: pct(x0, FRAME_W), top: pct(y0 * zoom, FRAME_H), width: pct(x1 - x0, FRAME_W), height: pct((y1 - y0) * zoom, FRAME_H) };
}

const HEADER = box(235, 62, 850, 135);
const HEADER_COMPACT = box(235, 62, 850, 135, COMPACT_ZOOM);
const ART = box(81, 167, 978, 631);
const ART_COMPACT = box(81, 167, 978, 631, COMPACT_ZOOM);
const STAT_COLUMNS = [box(70, 668, 375, 800), box(375, 668, 686, 800), box(686, 668, 990, 800)];
const PASSIVE = box(100, 820, 960, 938);
/** The three ability holes in the frame (see-through). */
const ABILITY_SLOTS = [box(101, 972, 960, 1057), box(101, 1090, 960, 1177), box(100, 1208, 959, 1298)];
/** The Ascension plate, redrawn on top so the tier tint leaves it alone. */
const PLATE_CLIP = "inset(86% 30% 2% 30%)";

/** The tint laid over the frame's grey metal for each tier; Common keeps the grey. */
const TIER_TINTS: Record<string, string> = {
  rare: "#4caf50",
  unique: "#2196f3",
  royal: "#9c27b0",
  legendary: "#ffd700",
  forbidden: "#f44336",
};
/** Behind an ability's slot, by its category. */
const CATEGORY_FILLS: Record<string, string> = {
  ATTACK: "#8f2a2a",
  DEFENSE: "#2a5a9a",
  SUPPORT: "#2f7a3f",
  FLEE: "#b8601a",
  INTERCEPT: "#6a3fa0",
};
const DEFAULT_FILL = "#3a3e46";

// 24x24 stroke icons, as path data.
const STAT_ICONS = {
  hp: ["M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"],
  essence: ["M12 3c1 3 5 5 5 9a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-8z"],
  speed: ["M4 20C4 11 10 5 20 4c0 9-6 15-14 15", "M4 20L14 10"],
} as const;
const CATEGORY_ICONS: Record<string, readonly string[]> = {
  ATTACK: ["M14.5 17.5L3 6V3h3l11.5 11.5", "M13 19l6-6", "M16 16l4 4", "M19 21l2-2"],
  DEFENSE: ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"],
  SUPPORT: ["M12 19V5", "M6 11l6-6 6 6"],
  FLEE: ["M5 12h14", "M13 6l6 6-6 6"],
  INTERCEPT: ["M12 3v4", "M12 17v4", "M3 12h4", "M17 12h4", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
};

const STATS = [
  { key: "hp", label: "HP" },
  { key: "essence", label: "Essence" },
  { key: "speed", label: "Speed" },
] as const;
const stats = computed(() =>
  STATS.map((s, i) => ({
    ...s,
    value: props.ascended.base[s.key] ?? 0,
    growth: props.ascended.growth[s.key] ?? 0,
    icon: STAT_ICONS[s.key],
    style: STAT_COLUMNS[i],
  })),
);
const tint = computed(() => TIER_TINTS[props.tierId] ?? null);
const tintStyle = computed(() => ({
  background: tint.value ?? "transparent",
  maskImage: `url(${frameUrl})`,
  WebkitMaskImage: `url(${frameUrl})`,
}));
const art = computed(() => ascendedArt(props.ascended.id));
const artPosition = computed(() => `50% ${(props.compact ? art.value?.focusCompact : art.value?.focus) ?? 50}%`);
const tierVar = computed(() => `var(--em-tier-${props.tierId}, var(--em-tier-common))`);
const passiveName = computed(() => titleCase(props.ascended.passive.kind));
const passive = computed(() => passiveText(props.ascended.passive.kind, props.ascended.passive.params));
const abilities = computed(() =>
  props.ascended.abilities.slice(0, ABILITY_SLOTS.length).map((a, i) => ({
    ability: a,
    effect: abilityEffect(a),
    slot: ABILITY_SLOTS[i],
    fill: { ...ABILITY_SLOTS[i], background: CATEGORY_FILLS[a.category] ?? DEFAULT_FILL },
    icon: CATEGORY_ICONS[a.category] ?? [],
  })),
);
</script>

<template>
  <article
    class="card"
    :class="[`tier-${tierId}`, { compact }]"
    :style="{ '--tier': tierVar }"
    :aria-label="`${ascended.name}, ${titleCase(tierId)}, level ${level}`"
  >
    <div class="behind art-fill" :style="compact ? ART_COMPACT : ART" aria-hidden="true">
      <img v-if="art" class="portrait" :src="art.url" :style="{ objectPosition: artPosition }" alt="" draggable="false" />
      <template v-else>
        <span class="letter">{{ ascended.name.slice(0, 1) }}</span>
        <small v-if="!compact">Artwork</small>
      </template>
    </div>
    <template v-if="!compact">
      <div v-for="a in abilities" :key="a.ability.id" class="behind" :style="a.fill" aria-hidden="true" />
    </template>

    <img class="frame" :src="frameUrl" alt="" draggable="false" />
    <div v-if="tint" class="tint" :style="tintStyle" aria-hidden="true" />
    <img v-if="tint && !compact" class="frame plate" :src="frameUrl" alt="" draggable="false" :style="{ clipPath: PLATE_CLIP }" />

    <footer v-if="compact" class="tier-plate em-pixel">{{ titleCase(tierId) }}</footer>

    <header class="header" :style="compact ? HEADER_COMPACT : HEADER">
      <h4 class="ascended-name">{{ ascended.name }}</h4>
      <span v-if="!compact || showLevel" class="level">Lv {{ level }}</span>
    </header>

    <dl v-if="!compact" class="stat-list">
      <div v-for="s in stats" :key="s.key" class="stat" :style="s.style">
        <dt>
          <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in s.icon" :key="d" :d="d" /></svg>
          {{ s.label }}
        </dt>
        <dd>{{ s.value }}</dd>
        <span class="growth">+{{ s.growth }} / lvl</span>
      </div>
    </dl>

    <p v-if="!compact" class="passive" :style="PASSIVE" :title="`${passiveName}: ${passive}`">
      <strong :class="{ alone: passive === passiveName }">{{ passiveName }}</strong>
      <template v-if="passive !== passiveName">{{ ` ${passive}` }}</template>
    </p>

    <template v-if="!compact">
      <div v-for="a in abilities" :key="a.ability.id" class="ability" :style="a.slot">
        <span class="slot" aria-hidden="true">
          <svg class="icon" viewBox="0 0 24 24"><path v-for="d in a.icon" :key="d" :d="d" /></svg>
        </span>
        <div class="ability-text">
          <strong>{{ a.ability.name }}</strong>
          <span>{{ a.effect }}</span>
        </div>
        <span class="unlock">Lv {{ a.ability.unlock_level }}</span>
      </div>
    </template>
  </article>
</template>

<style scoped>
/* Sizes are in cqw (a percent of the card's width), so the text scales with the card. */
.card {
  container-type: inline-size;
  position: relative;
  isolation: isolate;
  width: var(--card-width, 440px);
  aspect-ratio: 1060 / 1484;
  color: #e8e8ea;
  text-align: left;
}
.card.compact {
  width: var(--card-width, 150px);
  overflow: hidden;
}
.compact .frame,
.compact .tint {
  height: 190%;
}
.portrait {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  user-select: none;
}
.tier-plate {
  position: absolute;
  right: 9%;
  bottom: 5%;
  left: 9%;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 14%;
  border: 1px solid var(--tier);
  background: #17222e;
  box-shadow: inset 0 0 0 2px #101720;
  font-size: 5.8cqw;
  letter-spacing: 0.3cqw;
  text-transform: uppercase;
  color: var(--tier);
}
.compact .level {
  font-size: 5.5cqw;
}
.compact .ascended-name {
  font-size: 7.5cqw;
}
.compact .letter {
  font-size: 34cqw;
}
.frame,
.tint {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  user-select: none;
}
.tint {
  mix-blend-mode: color;
  mask-size: 100% 100%;
  -webkit-mask-size: 100% 100%;
  pointer-events: none;
}
.behind {
  position: absolute;
}
.art-fill {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5cqw;
  color: #6d727b;
  background: #20242b;
}
.letter {
  font-size: 16cqw;
  font-weight: 600;
  line-height: 1;
  color: var(--em-accent);
}
.art-fill small {
  font-size: 2.4cqw;
  letter-spacing: 0.4cqw;
  text-transform: uppercase;
}
.header {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2cqw;
  color: #1b1d21;
}
.ascended-name {
  margin: 0;
  overflow: hidden;
  font-size: 4.4cqw;
  font-weight: 600;
  letter-spacing: 0.15cqw;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}
.level {
  flex: none;
  font-size: 3cqw;
  font-weight: 600;
}
.stat {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #1b1d21;
}
.stat dt {
  display: flex;
  align-items: center;
  gap: 0.8cqw;
  font-size: 2.3cqw;
  line-height: 1.1;
  letter-spacing: 0.3cqw;
  text-transform: uppercase;
  color: #3a3e46;
}
.stat dd {
  margin: 0;
  font-size: 4.4cqw;
  font-weight: 600;
  line-height: 1.05;
}
.growth {
  font-size: 2.2cqw;
  line-height: 1.1;
  color: #3a3e46;
}
.icon {
  width: 3cqw;
  height: 3cqw;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
/* The passive box holds four lines; it is cut after that, in full in its tooltip. */
.passive {
  position: absolute;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  margin: 0;
  overflow: hidden;
  font-size: 2.4cqw;
  font-weight: 500;
  line-height: 1.15;
  color: #1b1d21;
}
.passive strong {
  font-weight: 700;
  letter-spacing: 0.1cqw;
  text-transform: uppercase;
}
.passive strong:not(.alone)::after {
  content: " \2014";
}
.ability {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 2cqw;
  box-sizing: border-box;
  padding: 0 3cqw 0 2.5cqw;
}
.slot {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 6.4cqw;
  height: 6.4cqw;
  border: 0.4cqw solid #0f1012;
  border-radius: var(--em-radius);
  color: #ffb27a;
  background: #23262b;
}
.ability-text {
  flex: 1;
  min-width: 0;
}
.ability-text strong {
  display: block;
  font-size: 3cqw;
  letter-spacing: 0.15cqw;
  text-transform: uppercase;
  text-shadow: 0 0 0.6cqw #000;
}
.ability-text span {
  display: block;
  overflow: hidden;
  font-size: 2.4cqw;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #f0f0f2;
  text-shadow: 0 0 0.6cqw #000;
}
.unlock {
  flex: none;
  padding: 0.2cqw 1.8cqw;
  border: 0.35cqw solid #0f1012;
  border-radius: var(--radius-full);
  font-size: 2.4cqw;
  color: #ffb27a;
  background: #23262b;
}
</style>
