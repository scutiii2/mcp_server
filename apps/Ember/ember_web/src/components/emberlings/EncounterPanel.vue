<script setup lang="ts">
import { computed, ref } from "vue";
import type { BattleMode } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useEmberlingsStore } from "../../stores/emberlings";
import { formatCountdown, titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import SegmentedControl from "../SegmentedControl.vue";
import TierBadge from "./TierBadge.vue";

/** The Battle tab without a battle: look for a wild Spark (once the cooldown
 * is over), then decline it for free or fight it. Fight asks which Spark,
 * which preset, who plays and the highest EMBLEM tier the Spark may throw on
 * its own. mini_games needs a preset and a limit for autonomous play. */
const store = useEmberlingsStore();
const now = useNowSeconds();

const MODE_OPTIONS: { value: BattleMode; label: string }[] = [
  { value: "manual", label: "Manual" },
  { value: "autonomous", label: "Autonomous" },
];
const PRESET_SLOTS = [1, 2, 3, 4, 5];

const rollWait = computed(() => {
  const at = store.profile?.next_roll_at ?? null;
  return at === null ? 0 : Math.max(0, at - now.value);
});
const ready = computed(() =>
  (store.profile?.sparks ?? []).filter((s) => s.faint_until === null || s.faint_until <= now.value),
);
const tiers = computed(() => store.catalog?.tiers ?? []);

const formOpen = ref(false);
const sparkId = ref("");
const presetSlot = ref("none");
const mode = ref<BattleMode>("manual");
const emblemLimit = ref("none");
const autonomousIncomplete = computed(
  () => mode.value === "autonomous" && (presetSlot.value === "none" || emblemLimit.value === "none"),
);
const canFight = computed(() => sparkId.value !== "" && !autonomousIncomplete.value && !store.busy);

function openForm(): void {
  sparkId.value = ready.value[0]?.spark_id ?? "";
  presetSlot.value = "none";
  mode.value = "manual";
  emblemLimit.value = "none";
  formOpen.value = true;
}

async function fight(): Promise<void> {
  const current = store.encounter;
  if (current === null || !canFight.value) return;
  const view = await store.startBattle({
    encounter_id: current.id,
    spark_id: sparkId.value,
    preset_slot: presetSlot.value === "none" ? null : Number(presetSlot.value),
    mode: mode.value,
    emblem_limit: emblemLimit.value === "none" ? null : emblemLimit.value,
  });
  if (view !== null) formOpen.value = false;
}
</script>

<template>
  <section class="encounter-panel">
    <div v-if="!store.encounter" class="card look">
      <p class="muted">Wild Sparks roam nearby. Looking is free; you can look again after a short rest.</p>
      <button type="button" class="primary" :disabled="rollWait > 0 || store.busy" @click="store.rollEncounter()">
        {{ rollWait > 0 ? `Look again in ${formatCountdown(rollWait)}` : "Look for a wild Spark" }}
      </button>
    </div>

    <div v-else class="card preview">
      <div class="card-head">
        <h3>A wild {{ store.encounter.name }}</h3>
        <TierBadge :tier-id="store.encounter.tier_id" />
      </div>
      <p class="muted">Level {{ store.encounter.level }}. Its personalities stay hidden until you capture it.</p>
      <div class="buttons">
        <button type="button" class="chip" :disabled="store.busy" @click="store.declineEncounter()">Decline</button>
        <button type="button" class="primary" :disabled="store.busy || ready.length === 0" @click="openForm">Fight</button>
      </div>
      <p v-if="ready.length === 0" class="muted">All your Sparks are fainted. Wait until one is ready again.</p>
    </div>

    <BaseModal :open="formOpen" title="Start the battle" @close="formOpen = false">
      <form class="start-form" @submit.prevent="fight">
        <label>
          <span>Spark</span>
          <select v-model="sparkId" name="spark">
            <option v-for="s in ready" :key="s.spark_id" :value="s.spark_id">{{ s.name }} (level {{ s.level }})</option>
          </select>
        </label>
        <label>
          <span>Preset</span>
          <select v-model="presetSlot" name="preset">
            <option value="none">None</option>
            <option v-for="n in PRESET_SLOTS" :key="n" :value="String(n)">Preset {{ n }}</option>
          </select>
        </label>
        <SegmentedControl v-model="mode" :options="MODE_OPTIONS" label="Who plays" />
        <label>
          <span>EMBLEM limit</span>
          <select v-model="emblemLimit" name="limit">
            <option value="none">None</option>
            <option v-for="t in tiers" :key="t.id" :value="t.id">{{ titleCase(t.id) }}</option>
          </select>
        </label>
        <p class="muted hint">The highest EMBLEM tier your Spark may throw on its own.</p>
        <p v-if="autonomousIncomplete" class="error">Autonomous play needs a preset and an EMBLEM limit.</p>
        <div class="buttons">
          <button type="button" class="chip" @click="formOpen = false">Cancel</button>
          <button type="submit" class="primary" :disabled="!canFight">Fight</button>
        </div>
      </form>
    </BaseModal>
  </section>
</template>

<style scoped>
.look,
.preview {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.look p,
.preview p {
  margin: 0;
}
.preview .card-head {
  width: 100%;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.start-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.start-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
}
.start-form select {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.start-form select:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.hint {
  margin: -6px 0 0;
  font-size: 0.85em;
}
.start-form .buttons {
  justify-content: flex-end;
}
</style>
