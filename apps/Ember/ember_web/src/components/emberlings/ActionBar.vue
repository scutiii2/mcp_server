<script setup lang="ts">
import { computed, ref } from "vue";
import type { ActionChoice, BattleMode, BattleView, LegalAction } from "../../api/EmberlingsClient";
import { ROUND_PACE_MS, useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "../ConfirmModal.vue";
import SegmentedControl from "../SegmentedControl.vue";

/** Below the arena: who plays (manual or autonomous, switched between rounds),
 * Forfeit, and in manual mode one button per legal action. Abilities still
 * cooling down are shown disabled. A catch asks which EMBLEM to throw. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();

const BASIC_LABELS: Record<Exclude<LegalAction["kind"], "ability">, string> = {
  attack: "Attack",
  flee: "Flee",
  catch: "Catch",
};
const paceSeconds = ROUND_PACE_MS / 1000;

const active = computed(() => props.battle.status === "active");
const locked = computed(() => !active.value || props.battle.phase !== "choosing" || store.battleBusy);
const modeOptions = computed<{ value: BattleMode; label: string; disabled?: boolean }[]>(() => [
  { value: "manual", label: "Manual", disabled: locked.value },
  // mini_games needs an EMBLEM limit for autonomous play; a battle started without one stays manual.
  { value: "autonomous", label: "Autonomous", disabled: locked.value || props.battle.emblem_limit === null },
]);
const mode = computed<BattleMode>({
  get: () => props.battle.mode,
  set: (value) => {
    if (value !== props.battle.mode && !locked.value) void store.setMode(value);
  },
});
const coolingDown = computed(() => props.battle.player.abilities.filter((a) => !a.ready));
const ownedTiers = computed(() => (store.catalog?.tiers ?? []).filter((t) => (props.battle.emblems[t.id] ?? 0) > 0));
const catchOpen = ref(false);
const forfeitOpen = ref(false);

function label(action: LegalAction): string {
  if (action.kind === "ability") return action.name ?? titleCase(action.ability_id ?? "ability");
  return BASIC_LABELS[action.kind];
}

function choose(action: LegalAction): void {
  if (action.kind === "catch") {
    catchOpen.value = true;
    return;
  }
  const choice: ActionChoice =
    action.kind === "ability" && action.ability_id !== null ? { kind: "ability", ability_id: action.ability_id } : { kind: action.kind };
  void store.act(choice);
}

function throwEmblem(tier: string): void {
  catchOpen.value = false;
  void store.act({ kind: "catch", emblem_tier: tier });
}

function forfeit(): void {
  forfeitOpen.value = false;
  void store.forfeit();
}
</script>

<template>
  <section class="card action-bar">
    <div class="controls">
      <SegmentedControl v-model="mode" :options="modeOptions" label="Who plays" />
      <button type="button" class="danger" :disabled="!active || store.battleBusy" @click="forfeitOpen = true">Forfeit</button>
    </div>

    <p v-if="battle.mode === 'autonomous'" class="muted">Your Spark chooses on its own, one round every {{ paceSeconds }} seconds.</p>
    <div v-else class="actions">
      <button
        v-for="action in battle.actions"
        :key="`${action.kind}:${action.ability_id ?? ''}`"
        type="button"
        class="action"
        :disabled="locked"
        @click="choose(action)"
      >
        <span class="action-name">{{ label(action) }}</span>
        <span class="action-detail">{{ titleCase(action.category) }} · {{ action.percentage }}%</span>
      </button>
      <button v-for="ability in coolingDown" :key="`cooldown:${ability.id}`" type="button" class="action" disabled>
        <span class="action-name">{{ ability.name }}</span>
        <span class="action-detail">Cooling down ({{ ability.cooldown }} {{ ability.cooldown === 1 ? "round" : "rounds" }})</span>
      </button>
    </div>

    <BaseModal :open="catchOpen" title="Throw which EMBLEM?" @close="catchOpen = false">
      <p v-if="ownedTiers.length === 0" class="muted">You have no EMBLEMs. Buy some in the shop.</p>
      <div class="tiers">
        <button v-for="t in ownedTiers" :key="t.id" type="button" class="primary" @click="throwEmblem(t.id)">
          {{ titleCase(t.id) }} ({{ battle.emblems[t.id] }})
        </button>
      </div>
    </BaseModal>

    <ConfirmModal
      :open="forfeitOpen"
      title="Forfeit this battle?"
      message="It counts as a loss and your Spark faints for a while."
      confirm-label="Forfeit"
      :busy="store.battleBusy"
      @confirm="forfeit"
      @close="forfeitOpen = false"
    />
  </section>
</template>

<style scoped>
.action-bar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}
.action-bar > p {
  margin: 0;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}
.actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
}
button.action {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
button.action:hover:not(:disabled) {
  border-color: var(--accent);
}
button.action:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.action-name {
  font-weight: 600;
}
.action-detail {
  font-size: 0.8em;
  color: var(--muted);
}
.tiers {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (prefers-reduced-motion: reduce) {
  button.action {
    transition: none;
  }
}
</style>
