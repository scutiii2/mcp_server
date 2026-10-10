<script setup lang="ts">
import { computed, ref } from "vue";
import type { BattleMode, BattleView } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import EmButton from "./ui/EmButton.vue";
import EmConfirm from "./ui/EmConfirm.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmTabs from "./ui/EmTabs.vue";

/** Above the arena: who plays (manual or autonomous, switched between rounds) and
 * Forfeit, which asks first. A battle started without an EMBLEM limit stays manual:
 * mini_games needs a limit for autonomous play. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();

const active = computed(() => props.battle.status === "active");
const locked = computed(() => !active.value || props.battle.phase !== "choosing" || store.battleBusy);
const modeOptions = computed(() => [
  { value: "manual", label: "Manual", disabled: locked.value },
  { value: "autonomous", label: "Autonomous", disabled: locked.value || props.battle.emblem_limit === null },
]);
const forfeitOpen = ref(false);

function setMode(value: string): void {
  if (value !== props.battle.mode && !locked.value) void store.setMode(value as BattleMode);
}

function forfeit(): void {
  forfeitOpen.value = false;
  void store.forfeit();
}
</script>

<template>
  <div class="controls">
    <EmTabs :model-value="battle.mode" :options="modeOptions" aria-label="Who plays" @update:model-value="setMode" />
    <EmButton variant="danger" :disabled="!active || store.battleBusy" @click="forfeitOpen = true"><EmIcon name="battle" /> Forfeit</EmButton>

    <EmConfirm
      :open="forfeitOpen"
      title="Forfeit this battle?"
      message="It counts as a loss and your Ascended faints for a while."
      confirm-label="Forfeit battle"
      cancel-label="Keep battling"
      danger
      :busy="store.battleBusy"
      @confirm="forfeit"
      @close="forfeitOpen = false"
    />
  </div>
</template>

<style scoped>
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-3);
  margin-bottom: var(--em-space-4);
}
</style>
