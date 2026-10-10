<script setup lang="ts">
import { computed } from "vue";
import type { BattleView } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { RESULT_LABELS, titleCase } from "../../utils/emberlings";

/** A finished battle: the outcome, what it paid, the personalities a capture
 * revealed, and Back to the encounter screen. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();
const result = computed(() => props.battle.result);
const levelledUp = computed(() => {
  const r = result.value;
  return r?.level_before !== undefined && r.level_after !== undefined && r.level_after > r.level_before;
});
</script>

<template>
  <section v-if="result" class="card battle-result" role="status">
    <h3>{{ RESULT_LABELS[result.kind] }}</h3>
    <ul class="gains">
      <li v-if="result.xp !== undefined">
        +{{ result.xp }} XP for {{ battle.player.name }}<template v-if="levelledUp">, now level {{ result.level_after }}</template>
      </li>
      <li v-if="result.insignia !== undefined">+{{ result.insignia }} Insignia</li>
      <li v-if="result.copies_granted !== undefined">
        +{{ result.copies_granted }} {{ result.copies_granted === 1 ? "copy" : "copies" }} of {{ battle.wild.name
        }}<template v-if="result.tier_id">, now {{ titleCase(result.tier_id) }}</template>
      </li>
      <li v-if="result.faint_until !== undefined">{{ battle.player.name }} fainted and needs rest before its next battle.</li>
    </ul>
    <template v-if="result.revealed_personalities?.length">
      <h4>Personalities revealed</h4>
      <ul class="revealed">
        <li v-for="p in result.revealed_personalities" :key="p.id">
          {{ titleCase(p.type) }} · tier {{ p.tier }}<strong v-if="p.id === result.awarded_personality?.id"> (now yours)</strong>
        </li>
      </ul>
    </template>
    <button type="button" class="primary" @click="store.closeBattle()">Back</button>
  </section>
</template>

<style scoped>
.battle-result {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.battle-result h3,
.battle-result h4 {
  margin: 0;
}
.gains,
.revealed {
  margin: 0;
  padding-left: 18px;
}
</style>
