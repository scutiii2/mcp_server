<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import EmButton from "./ui/EmButton.vue";
import EmDialog from "./ui/EmDialog.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmNotice from "./ui/EmNotice.vue";
import EmRing from "./ui/EmRing.vue";

/** The five-second EMBLEM prompt over the arena: the tiers this battle's limit permits,
 * with owned counts, and a countdown (the store's, counted on this device). "Let my
 * Spark decide" only closes it; at zero the store calls advance and mini_games settles
 * the prompt (the Spark's choice, or a basic ATTACK). A tier you own none of is disabled. */
const store = useEmberlingsStore();
const dismissed = ref(false);
const prompt = computed(() => (store.promptOpen ? (store.battle?.prompt ?? null) : null));
const expired = computed(() => store.promptRemaining <= 0);
const seconds = computed(() => Math.ceil(store.promptRemaining));

watch(
  () => store.battle?.revision,
  () => {
    dismissed.value = false;
  },
);
</script>

<template>
  <EmDialog :open="prompt !== null && !dismissed" :title="expired ? 'Time is up' : 'Throw an EMBLEM?'" @close="dismissed = true">
    <div v-if="prompt" class="emblem-prompt">
      <EmRing :remaining="store.promptRemaining" :total="store.promptTotal" />
      <p class="lead">
        {{ expired ? "Your Spark will decide this turn." : `${store.battle?.player.name} wants to catch ${store.battle?.wild.name}. Pick an EMBLEM, or let your Spark decide.` }}
      </p>
      <div class="tiers">
        <EmButton
          v-for="tier in prompt.permitted_tiers"
          :key="tier"
          class="tier"
          :style="{ '--tier': `var(--em-tier-${tier}, var(--em-tier-normal))` }"
          :disabled="expired || store.battleBusy || (prompt.owned[tier] ?? 0) === 0"
          @click="store.answerEmblem(tier)"
        >
          <span class="name"><EmIcon name="flame" /> {{ titleCase(tier) }}</span>
          <span class="count em-num">{{ prompt.owned[tier] ?? 0 }} owned</span>
        </EmButton>
      </div>
      <p v-if="prompt.permitted_tiers.length === 0" class="caption">You own no EMBLEM within this battle's limit.</p>
      <p v-else class="caption">Permitted tiers: {{ prompt.permitted_tiers.map(titleCase).join(", ") }}</p>
      <EmButton class="decide" @click="dismissed = true">{{ expired ? "Waiting for your Spark…" : "Let my Spark decide" }}</EmButton>
      <EmNotice>{{ expired ? "Your Spark is choosing an action." : `Choose within 5 seconds. ${seconds} s left.` }}</EmNotice>
    </div>
  </EmDialog>
</template>

<style scoped>
.emblem-prompt {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--em-space-3);
}
.emblem-prompt > :first-child {
  align-self: center;
}
.lead {
  text-align: center;
  color: var(--em-muted);
}
.tiers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--em-space-3);
  margin: var(--em-space-3) 0 0;
}
.tier {
  justify-content: space-between;
  border-color: var(--tier);
  color: var(--tier);
}
.tier:disabled {
  border-color: var(--em-disabled-border);
  color: var(--em-disabled-text);
}
.name {
  display: inline-flex;
  align-items: center;
  gap: var(--em-space-2);
}
.count {
  font-weight: 400;
}
.caption {
  text-align: center;
  font-size: 12px;
  color: var(--em-muted);
}
@media (max-width: 700px) {
  .tier {
    padding: 10px;
    font-size: 12px;
  }
}
</style>
