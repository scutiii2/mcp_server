<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import CountdownRing from "../CountdownRing.vue";

/** The five-second EMBLEM prompt over the arena: the tiers this battle's
 * limit permits, with owned counts and a countdown (the store's, counted on
 * this device). "Let my Spark decide" only closes it; at zero the store calls
 * advance and mini_games settles the prompt (the Spark's choice, or a basic ATTACK). */
const store = useEmberlingsStore();
const dismissed = ref(false);
const prompt = computed(() => (store.promptOpen ? (store.battle?.prompt ?? null) : null));
const expired = computed(() => store.promptRemaining <= 0);

watch(
  () => store.battle?.revision,
  () => {
    dismissed.value = false;
  },
);
</script>

<template>
  <BaseModal :open="prompt !== null && !dismissed" title="Throw an EMBLEM?" @close="dismissed = true">
    <div v-if="prompt" class="emblem-prompt">
      <div class="timer">
        <CountdownRing :remaining="store.promptRemaining" :total="store.promptTotal" />
        <span>{{ expired ? "Time is up" : `${Math.ceil(store.promptRemaining)} s left` }}</span>
      </div>
      <p class="muted">
        {{ store.battle?.player.name }} wants to catch {{ store.battle?.wild.name }}. Pick an EMBLEM, or let your Spark decide.
      </p>
      <div class="tiers">
        <button
          v-for="tier in prompt.permitted_tiers"
          :key="tier"
          type="button"
          class="primary"
          :disabled="expired || store.battleBusy"
          @click="store.answerEmblem(tier)"
        >
          {{ titleCase(tier) }} ({{ prompt.owned[tier] ?? 0 }})
        </button>
      </div>
      <p v-if="prompt.permitted_tiers.length === 0" class="muted">You own no EMBLEM within this battle's limit.</p>
      <button type="button" class="chip" @click="dismissed = true">Let my Spark decide</button>
    </div>
  </BaseModal>
</template>

<style scoped>
.emblem-prompt {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}
.emblem-prompt p {
  margin: 0;
}
.timer {
  display: flex;
  align-items: center;
  gap: 8px;
  font-variant-numeric: tabular-nums;
}
.tiers {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
