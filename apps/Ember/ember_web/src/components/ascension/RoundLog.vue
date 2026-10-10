<script setup lang="ts">
import { computed } from "vue";
import type { BattleView } from "../../api/AscensionClient";
import { describeAction, describeEvent } from "../../utils/ascension";
import EmIcon from "./ui/EmIcon.vue";
import EmPanel from "./ui/EmPanel.vue";

/** The battle's revealed rounds in words, latest first. Each round lists what both
 * Ascended chose, then what happened. It is a polite live region and does not scroll by
 * itself. */
const props = defineProps<{ battle: BattleView }>();
const names = computed(() => ({ player: props.battle.player.name, wild: props.battle.wild.name }));
const rounds = computed(() => [...props.battle.history].reverse());
const pad = (round: number) => `R${String(round).padStart(2, "0")}`;
</script>

<template>
  <EmPanel class="round-log">
    <div class="head">
      <h3>Round log</h3>
      <small>Latest first <EmIcon name="arrow" :size="14" class="down" /></small>
    </div>
    <p v-if="battle.history.length === 0" class="empty">No rounds yet.</p>
    <ol v-else class="rounds" aria-live="polite">
      <li v-for="entry in rounds" :key="entry.round" class="round">
        <p class="line title">
          <span class="rn em-num">{{ pad(entry.round) }}</span>
          <span>Round {{ entry.round }}: {{ names.player }} chose {{ describeAction(entry.actions.player[0], battle.player.abilities) }}, {{ names.wild }} chose {{ describeAction(entry.actions.wild[0], battle.wild.abilities) }}</span>
        </p>
        <p v-for="(event, index) in entry.events" :key="index" class="line">
          <span class="rn em-num">{{ pad(entry.round) }}</span>
          <span>{{ describeEvent(event, names) }}</span>
        </p>
      </li>
    </ol>
  </EmPanel>
</template>

<style scoped>
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--em-space-3);
  margin-bottom: var(--em-space-4);
}
.head h3 {
  margin: 0;
  font-size: 18px;
}
.head small {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--em-muted);
}
.down {
  transform: rotate(90deg);
}
.empty {
  color: var(--em-muted);
}
.rounds {
  display: grid;
  gap: 0;
  max-height: 260px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}
.line {
  display: flex;
  gap: var(--em-space-3);
  padding: 8px 0;
  border-bottom: 1px solid var(--em-divider);
  font-size: 13px;
}
.rn {
  flex: none;
  width: 34px;
  font-size: 12px;
  color: var(--em-muted);
}
.title {
  font-weight: 600;
}
</style>
