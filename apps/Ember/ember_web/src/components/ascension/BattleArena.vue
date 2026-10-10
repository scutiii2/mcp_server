<script setup lang="ts">
import { computed } from "vue";
import type { BattleView, Buff, Fighter } from "../../api/AscensionClient";
import { ascendedArt } from "./ascendedArt";
import EmBar from "./ui/EmBar.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";

/** Both Ascended facing each other across a VS marker: name, level, tier, health, their
 * portrait, and what is affecting them (buffs, defense). The numbers are always written. */
const props = defineProps<{ battle: BattleView }>();

const sides = computed<{ key: string; label: string; fighter: Fighter }[]>(() => [
  { key: "player", label: "You", fighter: props.battle.player },
  { key: "wild", label: "Wild", fighter: props.battle.wild },
]);

function buffText(buff: Buff): string {
  const lasting =
    buff.rounds_left === null ? " for the whole battle" : `, ${buff.rounds_left} ${buff.rounds_left === 1 ? "round" : "rounds"} left`;
  return `+${buff.amount} ${buff.stat}${lasting}`;
}

function effects(fighter: Fighter): string[] {
  const list = fighter.buffs.map(buffText);
  if (fighter.defense) {
    const d = fighter.defense;
    list.push(`Defense ${d.rating}: ${d.attacks_left} attacks or ${d.rounds_left} rounds left`);
  }
  return list;
}

function art(fighter: Fighter): string | null {
  return ascendedArt(fighter.ascended_id)?.url ?? null;
}
</script>

<template>
  <section class="arena" :aria-label="`Round ${battle.round}`">
    <div class="fighters">
      <template v-for="(side, i) in sides" :key="side.key">
        <div v-if="i === 1" class="versus em-pixel" aria-hidden="true">VS</div>
        <article class="fighter" :class="side.key" :aria-label="`${side.label}: ${side.fighter.name}`">
          <div class="head">
            <h3>{{ side.fighter.name }} <small class="em-num">Lv. {{ side.fighter.level }}</small></h3>
            <EmTierBadge :tier-id="side.fighter.tier_id" />
          </div>
          <EmBar kind="hp" :value="side.fighter.hp" :max="side.fighter.max_hp" :label="`${side.fighter.name} health`" />
          <p class="hp em-num">HP {{ side.fighter.hp }} / {{ side.fighter.max_hp }}</p>
          <div class="art">
            <img v-if="art(side.fighter)" :src="art(side.fighter)!" alt="" draggable="false" />
            <span v-else class="letter" aria-hidden="true">{{ side.fighter.name.slice(0, 1) }}</span>
          </div>
          <p class="stats em-num">Essence {{ side.fighter.essence }} · Speed {{ side.fighter.speed }}</p>
          <ul v-if="effects(side.fighter).length" class="effects">
            <li v-for="text in effects(side.fighter)" :key="text">{{ side.label }} · {{ text }}</li>
          </ul>
        </article>
      </template>
    </div>
  </section>
</template>

<style scoped>
.arena {
  padding: var(--em-space-5);
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  background:
    radial-gradient(ellipse at 50% 90%, #36424b, transparent 70%),
    linear-gradient(#152332, #101720);
}
.fighters {
  display: grid;
  grid-template-columns: 1fr 60px 1fr;
  align-items: start;
  gap: var(--em-space-5);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-2);
  margin-bottom: var(--em-space-2);
}
.head h3 {
  margin: 0;
  font-size: 18px;
}
.head small {
  font-size: 12px;
  color: var(--em-muted);
}
.hp {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--em-muted);
}
.art {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 230px;
  margin-top: var(--em-space-3);
}
.art img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  mix-blend-mode: lighten;
}
.wild .art img {
  transform: scaleX(-1);
}
.letter {
  font-size: 80px;
  font-weight: 600;
  color: var(--em-accent);
}
.versus {
  align-self: center;
  text-align: center;
  font-size: 24px;
  color: var(--em-accent);
}
.stats {
  margin: var(--em-space-2) 0 0;
  font-size: 12px;
  color: var(--em-muted);
}
.effects {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
  color: var(--em-muted);
}
@media (max-width: 700px) {
  .arena {
    padding: 18px;
  }
  .fighters {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
  .versus {
    order: 2;
    margin: 12px 0;
    font-size: 18px;
  }
  .wild {
    order: 3;
  }
  .art {
    height: 155px;
  }
}
</style>
