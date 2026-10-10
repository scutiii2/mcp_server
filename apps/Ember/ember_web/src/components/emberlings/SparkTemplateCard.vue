<script setup lang="ts">
import { computed } from "vue";
import type { SparkInfo } from "../../api/EmberlingsClient";
import { abilityEffect, passiveText, titleCase } from "../../utils/emberlings";

/** A Spark's card, laid out like the front card template
 * (apps/mini_games/sparks/spark_normal_front_template.png): header, artwork,
 * HP / Essence / Speed, passive and three abilities. Fixed size, so the real
 * image can replace this frame later with the same text laid over it. */
const props = withDefaults(defineProps<{ spark: SparkInfo; level?: number; tierId?: string }>(), {
  level: 1,
  tierId: "normal",
});

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
};
const PASSIVE_ICON = ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"];

const STATS = [
  { key: "hp", label: "HP" },
  { key: "essence", label: "Essence" },
  { key: "speed", label: "Speed" },
] as const;
const stats = computed(() =>
  STATS.map((s) => ({
    ...s,
    value: props.spark.base[s.key] ?? 0,
    growth: props.spark.growth[s.key] ?? 0,
    icon: STAT_ICONS[s.key],
  })),
);
</script>

<template>
  <article class="card" :aria-label="`${spark.name}, level ${level}`">
    <header class="header">
      <h4 class="spark-name">{{ spark.name }}</h4>
      <span class="header-end"><span class="tier">{{ titleCase(tierId) }}</span>Lv {{ level }}</span>
    </header>

    <div class="art" aria-hidden="true">
      <span class="letter">{{ spark.name.slice(0, 1) }}</span>
      <small>Artwork</small>
    </div>

    <dl class="stats">
      <div v-for="s in stats" :key="s.key" class="stat">
        <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in s.icon" :key="d" :d="d" /></svg>
        <dt>{{ s.label }}</dt>
        <dd>{{ s.value }}</dd>
        <span class="growth">+{{ s.growth }} / lvl</span>
      </div>
    </dl>

    <div class="passive">
      <span class="slot" aria-hidden="true">
        <svg class="icon" viewBox="0 0 24 24"><path v-for="d in PASSIVE_ICON" :key="d" :d="d" /></svg>
      </span>
      <div>
        <strong>{{ titleCase(spark.passive.kind) }}</strong>
        <span :title="passiveText(spark.passive.kind, spark.passive.params)">{{
          passiveText(spark.passive.kind, spark.passive.params)
        }}</span>
      </div>
    </div>

    <ul class="abilities">
      <li v-for="a in spark.abilities" :key="a.id" class="ability">
        <span class="slot" aria-hidden="true">
          <svg class="icon" viewBox="0 0 24 24">
            <path v-for="d in CATEGORY_ICONS[a.category] ?? []" :key="d" :d="d" />
          </svg>
        </span>
        <div class="ability-text">
          <strong>{{ a.name }}</strong>
          <span>{{ abilityEffect(a) }}</span>
        </div>
        <span class="unlock">Lv {{ a.unlock_level }}</span>
      </li>
    </ul>

    <footer class="plate">Emberlings</footer>
  </article>
</template>

<style scoped>
/* The template is 263 x 371; this keeps its proportions at a size the text can read at.
 * Every section has a fixed height (the artwork takes what is left), so a long
 * passive never moves the rest: it is cut after five lines, in full in its tooltip. */
.card {
  --frame: #565b64;
  --frame-edge: #1b1d21;
  --frame-light: #9aa0a8;
  --panel-light: #b9bec5;
  --panel-pale: #c9cdd2;
  --panel-dark: #3a3e46;
  --slot: #23262b;
  --ink: #1b1d21;
  --ink-soft: #2a2d33;
  --steel-text: #e8e8ea;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 340px;
  height: 480px;
  padding: 9px;
  border: 3px solid var(--frame-edge);
  border-radius: var(--radius-md);
  outline: 2px solid var(--frame-light);
  outline-offset: -5px;
  color: var(--steel-text);
  background: var(--frame);
  text-align: left;
}
.header {
  flex: none;
  box-sizing: border-box;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 3px 7px;
  border: 2px solid var(--ink-soft);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--panel-light);
}
.spark-name {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.header-end {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  white-space: nowrap;
}
.tier {
  padding: 0 6px;
  border-radius: var(--radius-md);
  font-size: 10px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--steel-text);
  background: var(--panel-dark);
}
.art {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 60px;
  border: 2px solid #34383f;
  border-radius: var(--radius-sm);
  color: #6d727b;
  background: #20242b;
}
.letter {
  font-size: 34px;
  font-weight: 600;
  line-height: 1;
  color: var(--accent);
}
.art small {
  font-size: 10px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}
.stats {
  flex: none;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0;
  border: 2px solid var(--ink-soft);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--panel-light);
}
.stat {
  display: grid;
  justify-items: center;
  padding: 3px 2px;
  border-left: 1.5px solid #8a8f98;
}
.stat:first-child {
  border-left: 0;
}
.stat dt {
  font-size: 9px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--panel-dark);
}
.stat dd {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.2;
}
.growth {
  font-size: 10px;
  color: var(--panel-dark);
}
.icon {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.slot {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 2px solid #0f1012;
  border-radius: var(--radius-sm);
  color: var(--accent);
  background: var(--slot);
}
.passive,
.ability {
  display: flex;
  align-items: center;
  gap: 7px;
  border-radius: var(--radius-sm);
}
.passive {
  flex: none;
  box-sizing: border-box;
  height: 104px;
  overflow: hidden;
  align-items: flex-start;
  padding: 5px 7px;
  border: 2px solid var(--ink-soft);
  color: var(--ink);
  background: var(--panel-pale);
}
.passive strong,
.ability strong {
  display: block;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
}
.passive span:not(.slot) {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 5;
  line-clamp: 5;
  overflow: hidden;
  font-size: 11px;
  line-height: 1.35;
  color: var(--ink-soft);
}
.abilities {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.ability {
  flex: none;
  box-sizing: border-box;
  height: 40px;
  padding: 4px 7px;
  border: 2px solid var(--frame-edge);
  background: var(--panel-dark);
}
.ability-text {
  flex: 1;
  min-width: 0;
}
.ability-text span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--panel-light);
}
.unlock {
  flex: none;
  padding: 1px 7px;
  border: 1.5px solid #0f1012;
  border-radius: var(--radius-md);
  font-size: 10px;
  color: #ffb27a;
  background: var(--slot);
}
.plate {
  flex: none;
  align-self: center;
  padding: 1px 14px;
  border: 2px solid #0f1012;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--accent);
  background: var(--slot);
}
</style>
