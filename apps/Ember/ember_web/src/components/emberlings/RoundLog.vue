<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { BattleView } from "../../api/EmberlingsClient";
import { describeAction, describeEvent } from "../../utils/emberlings";

/** The battle's revealed rounds in words, oldest first; new rounds scroll into view. */
const props = defineProps<{ battle: BattleView }>();
const names = computed(() => ({ player: props.battle.player.name, wild: props.battle.wild.name }));
const list = ref<HTMLElement | null>(null);

watch(
  () => props.battle.history.length,
  async () => {
    await nextTick();
    if (list.value) list.value.scrollTop = list.value.scrollHeight;
  },
);
</script>

<template>
  <section class="round-log">
    <h4>Round log</h4>
    <p v-if="battle.history.length === 0" class="muted">No rounds yet.</p>
    <ol v-else ref="list" class="rounds" aria-live="polite">
      <li v-for="entry in battle.history" :key="entry.round">
        <p class="round-title">
          Round {{ entry.round }}: {{ names.player }} chose {{ describeAction(entry.actions.player[0], battle.player.abilities) }},
          {{ names.wild }} chose {{ describeAction(entry.actions.wild[0], battle.wild.abilities) }}
        </p>
        <ul class="events">
          <li v-for="(event, index) in entry.events" :key="index">{{ describeEvent(event, names) }}</li>
        </ul>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.round-log h4 {
  margin: 0 0 6px;
}
.rounds {
  max-height: 260px;
  margin: 0;
  padding: 8px 12px 8px 32px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
}
.round-title {
  margin: 6px 0 2px;
  font-weight: 600;
}
.events {
  margin: 0;
  padding-left: 18px;
  font-size: 0.9em;
  color: var(--muted);
}
</style>
