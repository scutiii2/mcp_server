<script setup lang="ts">
import { computed, ref } from "vue";
import type { ActionChoice, BattleView, LegalAction } from "../../api/EmberlingsClient";
import { ROUND_PACE_MS, useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import EmButton from "./ui/EmButton.vue";
import EmDialog from "./ui/EmDialog.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmPanel from "./ui/EmPanel.vue";

/** "Your move": in manual mode one button per legal action, in the colour of its
 * category (the category is also written). Abilities still cooling down are shown
 * disabled with how long. A catch asks which EMBLEM to throw. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();

const BASIC_LABELS: Record<Exclude<LegalAction["kind"], "ability">, string> = {
  attack: "Attack",
  flee: "Flee",
  catch: "Catch",
};
const BASIC_NOTES: Record<string, string> = { flee: "Try to escape", catch: "Choose an EMBLEM" };
const paceSeconds = ROUND_PACE_MS / 1000;

const locked = computed(() => props.battle.status !== "active" || props.battle.phase !== "choosing" || store.battleBusy);
const coolingDown = computed(() => props.battle.player.abilities.filter((a) => !a.ready));
const ownedTiers = computed(() => (store.catalog?.tiers ?? []).filter((t) => (props.battle.emblems[t.id] ?? 0) > 0));
const catchOpen = ref(false);

function label(action: LegalAction): string {
  if (action.kind === "ability") return action.name ?? titleCase(action.ability_id ?? "ability");
  return BASIC_LABELS[action.kind];
}

function detail(action: LegalAction): string {
  if (action.kind === "flee" || action.kind === "catch") return BASIC_NOTES[action.kind]!;
  return `${titleCase(action.category)} · ${action.percentage}%`;
}

function categoryOf(action: LegalAction): string {
  return action.kind === "flee" ? "flee" : action.kind === "catch" ? "catch" : action.category.toLowerCase();
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
</script>

<template>
  <EmPanel class="action-bar">
    <div class="head">
      <h3>Your move</h3>
      <small class="em-num">Round {{ battle.round }}</small>
    </div>

    <p v-if="battle.mode === 'autonomous'" class="muted">Your Ascended chooses on its own, one round every {{ paceSeconds }} seconds.</p>
    <div v-else class="actions">
      <button
        v-for="action in battle.actions"
        :key="`${action.kind}:${action.ability_id ?? ''}`"
        type="button"
        class="action"
        :class="categoryOf(action)"
        :disabled="locked"
        @click="choose(action)"
      >
        <span class="action-name">{{ label(action) }}</span>
        <span class="action-detail">{{ detail(action) }}</span>
      </button>
      <button v-for="ability in coolingDown" :key="`cooldown:${ability.id}`" type="button" class="action" disabled>
        <span class="action-name">{{ ability.name }}</span>
        <span class="action-detail">Cooling down ({{ ability.cooldown }} {{ ability.cooldown === 1 ? "round" : "rounds" }})</span>
      </button>
    </div>

    <EmDialog :open="catchOpen" title="Throw which EMBLEM?" @close="catchOpen = false">
      <p v-if="ownedTiers.length === 0" class="muted none">You have no EMBLEMs. Buy some in the shop.</p>
      <div class="tiers">
        <EmButton v-for="t in ownedTiers" :key="t.id" variant="primary" @click="throwEmblem(t.id)">
          <EmIcon name="flame" /> {{ titleCase(t.id) }} ({{ battle.emblems[t.id] }})
        </EmButton>
      </div>
    </EmDialog>
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
  color: var(--em-muted);
}
.actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.action {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-height: var(--em-target);
  padding: 10px 6px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-raised);
  font: inherit;
  text-align: center;
  cursor: pointer;
  transition: background-color 120ms ease;
}
.action:hover:not(:disabled) {
  background: #2f4153;
}
.action-name {
  font-weight: 600;
}
.action-detail {
  font-size: 12px;
}
.action.attack {
  color: var(--em-cat-attack);
  border-color: var(--em-cat-attack);
}
.action.defense {
  color: var(--em-cat-defense);
  border-color: var(--em-cat-defense);
}
.action.support {
  color: var(--em-cat-support);
  border-color: var(--em-cat-support);
}
.action.flee {
  color: var(--em-cat-flee);
  border-color: var(--em-cat-flee);
}
.action.intercept {
  color: var(--em-cat-intercept);
  border-color: var(--em-cat-intercept);
}
.action.catch {
  color: var(--em-on-accent);
  border-color: var(--em-accent);
  background: var(--em-accent);
  box-shadow: 0 3px 0 var(--em-accent-edge);
}
.action:disabled {
  border-color: var(--em-disabled-border);
  color: var(--em-disabled-text);
  background: var(--em-disabled-surface);
  box-shadow: none;
  cursor: default;
}
.tiers {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-3);
}
.none {
  margin-bottom: var(--em-space-3);
}
@media (max-width: 700px) {
  .actions {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
