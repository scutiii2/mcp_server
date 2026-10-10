<script setup lang="ts">
import { computed } from "vue";
import type { Buff, BattleView, Fighter } from "../../api/EmberlingsClient";
import HealthBar from "./HealthBar.vue";
import RoundLog from "./RoundLog.vue";
import TierBadge from "./TierBadge.vue";

/** Both Sparks side by side (name, tier, level, health, essence, speed,
 * buffs, defense) above the round log. Text only, no art. */
const props = defineProps<{ battle: BattleView }>();

const sides = computed<{ key: string; label: string; fighter: Fighter }[]>(() => [
  { key: "player", label: "Your Spark", fighter: props.battle.player },
  { key: "wild", label: "Wild Spark", fighter: props.battle.wild },
]);

function buffText(buff: Buff): string {
  const lasting =
    buff.rounds_left === null ? " for the whole battle" : `, ${buff.rounds_left} ${buff.rounds_left === 1 ? "round" : "rounds"} left`;
  return `+${buff.amount} ${buff.stat}${lasting}`;
}
</script>

<template>
  <section class="arena">
    <p class="muted round">Round {{ battle.round }} · {{ battle.mode === "autonomous" ? "Autonomous" : "Manual" }}</p>
    <div class="fighters">
      <article v-for="side in sides" :key="side.key" class="card fighter" :aria-label="`${side.label}: ${side.fighter.name}`">
        <div class="card-head">
          <h3>{{ side.fighter.name }}</h3>
          <TierBadge :tier-id="side.fighter.tier_id" />
        </div>
        <p class="muted">{{ side.label }} · level {{ side.fighter.level }}</p>
        <HealthBar :hp="side.fighter.hp" :max-hp="side.fighter.max_hp" :label="`${side.fighter.name} health`" />
        <p class="stats">Essence {{ side.fighter.essence }} · Speed {{ side.fighter.speed }}</p>
        <ul v-if="side.fighter.buffs.length" class="effects">
          <li v-for="(buff, index) in side.fighter.buffs" :key="index">{{ buffText(buff) }}</li>
        </ul>
        <p v-if="side.fighter.defense" class="effects">
          Defense {{ side.fighter.defense.rating }}: {{ side.fighter.defense.attacks_left }} attacks or
          {{ side.fighter.defense.rounds_left }} rounds left
        </p>
      </article>
    </div>
    <RoundLog :battle="battle" />
  </section>
</template>

<style scoped>
.arena {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.round {
  margin: 0;
}
.fighters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.fighter {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
}
.fighter p {
  margin: 0;
}
.stats {
  font-size: 0.9em;
}
.effects {
  margin: 0;
  padding-left: 18px;
  font-size: 0.85em;
  color: var(--muted);
}
p.effects {
  padding-left: 0;
}
</style>
