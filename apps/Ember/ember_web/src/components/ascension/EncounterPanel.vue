<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { BattleMode } from "../../api/AscensionClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useAscensionStore } from "../../stores/ascension";
import { formatCountdown, titleCase } from "../../utils/ascension";
import AscendedTemplateCard from "./AscendedTemplateCard.vue";
import EmButton from "./ui/EmButton.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmNotice from "./ui/EmNotice.vue";
import EmPanel from "./ui/EmPanel.vue";
import EmTabs from "./ui/EmTabs.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";

/** The Battle tab without a battle, in three steps: look for a wild Ascended (once the
 * cooldown is over), see it and decline for free or fight, then set the battle up (which
 * Ascended, which preset, who plays and the highest EMBLEM tier the Ascended may throw on its
 * own). mini_games needs a preset and a limit for autonomous play. It reports the step
 * (`stage`) so the page can title it. */
export type EncounterStage = "look" | "preview" | "setup";
const emit = defineEmits<{ stage: [stage: EncounterStage] }>();

const store = useAscensionStore();
const now = useNowSeconds();

const MODE_OPTIONS = [
  { value: "manual", label: "Manual" },
  { value: "autonomous", label: "Autonomous" },
];
const PRESET_OPTIONS = [{ value: "none", label: "None" }, ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))];

const rollWait = computed(() => {
  const at = store.profile?.next_roll_at ?? null;
  return at === null ? 0 : Math.max(0, at - now.value);
});
const ascendeds = computed(() => store.profile?.ascendeds ?? []);
const ready = computed(() => ascendeds.value.filter((s) => s.faint_until === null || s.faint_until <= now.value));
const resting = computed(() => ascendeds.value.filter((s) => s.faint_until !== null && s.faint_until > now.value));
const tiers = computed(() => store.catalog?.tiers ?? []);
const ownedEmblems = computed(() =>
  tiers.value
    .filter((t) => (store.profile?.emblems[t.id] ?? 0) > 0)
    .map((t) => `${store.profile?.emblems[t.id]} ${titleCase(t.id)}`)
    .join(" · "),
);
const wildInfo = computed(() => store.catalog?.ascendeds.find((s) => s.id === store.encounter?.ascended_id) ?? null);

const formOpen = ref(false);
const ascendedId = ref("");
const presetSlot = ref("none");
const mode = ref<BattleMode>("manual");
const emblemLimit = ref("none");
const chosen = computed(() => ready.value.find((s) => s.ascended_id === ascendedId.value) ?? null);
const chosenInfo = computed(() => store.catalog?.ascendeds.find((s) => s.id === chosen.value?.ascended_id) ?? null);
const autonomousIncomplete = computed(
  () => mode.value === "autonomous" && (presetSlot.value === "none" || emblemLimit.value === "none"),
);
const canFight = computed(() => ascendedId.value !== "" && !autonomousIncomplete.value && !store.busy);
const limitHint = computed(() => {
  const index = tiers.value.findIndex((t) => t.id === emblemLimit.value);
  if (index === -1) return "Choose a limit to let your Ascended throw EMBLEMs on its own. Autonomous play needs one.";
  const names = tiers.value.slice(0, index + 1).map((t) => titleCase(t.id));
  const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
  return `Your Ascended may use ${list} EMBLEMs. Higher tiers stay in your wallet.`;
});
const stage = computed<EncounterStage>(() => (store.encounter === null ? "look" : formOpen.value ? "setup" : "preview"));
watch(stage, (value) => emit("stage", value), { immediate: true });
// A new encounter always starts at its preview.
watch(
  () => store.encounter?.id ?? null,
  () => {
    formOpen.value = false;
  },
);

function openForm(): void {
  ascendedId.value = ready.value[0]?.ascended_id ?? "";
  presetSlot.value = "none";
  mode.value = "manual";
  emblemLimit.value = "none";
  formOpen.value = true;
}

function setMode(value: string): void {
  mode.value = value as BattleMode;
}

async function fight(): Promise<void> {
  const current = store.encounter;
  if (current === null || !canFight.value) return;
  const view = await store.startBattle({
    encounter_id: current.id,
    ascended_id: ascendedId.value,
    preset_slot: presetSlot.value === "none" ? null : Number(presetSlot.value),
    mode: mode.value,
    emblem_limit: emblemLimit.value === "none" ? null : emblemLimit.value,
  });
  if (view !== null) formOpen.value = false;
}
</script>

<template>
  <section class="encounter-panel">
    <div v-if="stage === 'look'" class="split">
      <EmPanel class="look">
        <EmIcon name="battle" :size="40" class="big-icon" />
        <h3 class="em-pixel heading">Find a wild Ascended</h3>
        <p class="muted">Search for an opponent. Preview the Ascended before choosing to fight.</p>
        <EmButton variant="primary" :disabled="rollWait > 0 || store.busy" @click="store.rollEncounter()">
          <EmIcon :name="rollWait > 0 ? 'clock' : 'ascended'" />
          {{ rollWait > 0 ? `Search ready in ${formatCountdown(rollWait)}` : "Look for a wild Ascended" }}
        </EmButton>
        <p class="caption">Declining an encounter costs nothing.</p>
      </EmPanel>
      <EmPanel>
        <h3 class="em-pixel heading">Ready for battle?</h3>
        <p class="muted">Choose an Ascended that is rested and a preset that fits your plan.</p>
        <div class="facts">
          <div>
            <strong>{{ ready.length }} Ascended ready</strong>
            <p v-for="s in resting" :key="s.ascended_id" class="em-num">
              {{ s.name }} is fainted. Ready in {{ formatCountdown((s.faint_until ?? 0) - now) }}.
            </p>
            <p v-if="resting.length === 0">All rested.</p>
          </div>
          <div>
            <strong>{{ ownedEmblems || "No EMBLEMs" }}{{ ownedEmblems ? " EMBLEMs" : "" }}</strong>
            <p>Bring an EMBLEM if you hope to catch an Ascended.</p>
          </div>
        </div>
      </EmPanel>
    </div>

    <EmPanel v-else-if="stage === 'preview' && store.encounter" class="preview">
      <AscendedTemplateCard
        v-if="wildInfo"
        class="wild-card"
        :ascended="wildInfo"
        :level="store.encounter.level"
        :tier-id="store.encounter.tier_id"
        compact
        show-level
      />
      <div class="about">
        <p class="em-eyebrow">Wild encounter</p>
        <h3 class="em-pixel name">{{ store.encounter.name }}</h3>
        <p class="level em-num">Level {{ store.encounter.level }} · <EmTierBadge :tier-id="store.encounter.tier_id" /></p>
        <p class="muted">Its personalities stay hidden until you capture it.</p>
        <div class="buttons">
          <EmButton variant="primary" :disabled="store.busy || ready.length === 0" @click="openForm"><EmIcon name="battle" /> Fight</EmButton>
          <EmButton :disabled="store.busy" @click="store.declineEncounter()"><EmIcon name="arrow" /> Decline · free</EmButton>
        </div>
        <p v-if="ready.length === 0" class="caption">All your Ascended are fainted. Wait until one is ready again.</p>
        <p v-else class="caption">The encounter waits until you choose.</p>
      </div>
    </EmPanel>

    <form v-else class="start-form split" @submit.prevent="fight">
      <EmPanel>
        <h3 class="em-pixel heading">Choose your Ascended</h3>
        <div class="chosen">
          <AscendedTemplateCard v-if="chosenInfo && chosen" class="own-card" :ascended="chosenInfo" :level="chosen.level" :tier-id="chosen.tier_id" compact show-level />
          <div class="pick">
            <label class="field">
              <span>Your Ascended</span>
              <select v-model="ascendedId" name="ascended">
                <option v-for="s in ready" :key="s.ascended_id" :value="s.ascended_id">{{ s.name }} · {{ titleCase(s.tier_id) }} · Lv. {{ s.level }}</option>
              </select>
            </label>
            <p class="caption">Fainted Ascended are unavailable.</p>
          </div>
        </div>
        <ul v-if="resting.length" class="resting">
          <li v-for="s in resting" :key="s.ascended_id" class="em-num">{{ s.name }} · Fainted, ready in {{ formatCountdown((s.faint_until ?? 0) - now) }}</li>
        </ul>
      </EmPanel>

      <EmPanel>
        <h3 class="em-pixel heading">Battle plan</h3>
        <p class="label">Personality preset</p>
        <EmTabs v-model="presetSlot" class="wide" :options="PRESET_OPTIONS" aria-label="Personality preset" />
        <p class="label">Who plays?</p>
        <EmTabs :model-value="mode" class="wide" :options="MODE_OPTIONS" aria-label="Who plays" @update:model-value="setMode" />
        <label class="field">
          <span>Highest EMBLEM tier for Autonomous play</span>
          <select v-model="emblemLimit" name="limit">
            <option value="none">None</option>
            <option v-for="t in tiers" :key="t.id" :value="t.id">{{ titleCase(t.id) }} · up to {{ titleCase(t.id) }} EMBLEMs</option>
          </select>
        </label>
        <p class="caption">{{ limitHint }}</p>
        <EmNotice v-if="autonomousIncomplete" tone="error">Autonomous play needs a preset and an EMBLEM limit.</EmNotice>
        <div class="buttons">
          <EmButton type="submit" variant="primary" :disabled="!canFight"><EmIcon name="battle" /> Begin battle</EmButton>
          <EmButton @click="formOpen = false">Back</EmButton>
        </div>
      </EmPanel>
    </form>
  </section>
</template>

<style scoped>
.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--em-space-5);
  align-items: start;
}
.heading {
  margin: 0 0 var(--em-space-3);
  font-size: 18px;
  line-height: 1.4;
}
.look {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48px 24px;
  text-align: center;
}
.big-icon {
  margin-bottom: var(--em-space-3);
  color: var(--em-accent);
}
.look p {
  max-width: 360px;
  margin: 0 auto var(--em-space-4);
}
.caption {
  font-size: 12px;
  color: var(--em-muted);
}
.facts {
  display: grid;
  gap: 18px;
  margin-top: var(--em-space-4);
}
.facts > div {
  padding-bottom: 14px;
  border-bottom: 1px solid var(--em-divider);
}
.facts strong {
  display: block;
  margin-bottom: 3px;
}
.facts p {
  color: var(--em-muted);
}
.preview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-6);
  align-items: center;
}
.wild-card {
  --card-width: 190px;
  flex: none;
}
.about {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--em-space-3);
  min-width: 260px;
}
.name {
  margin: 0;
  font-size: 18px;
}
.level {
  display: flex;
  align-items: center;
  gap: var(--em-space-2);
  color: var(--em-muted);
  font-size: 16px;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-3);
  margin-top: var(--em-space-2);
}
.chosen {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-5);
  align-items: center;
}
.own-card {
  --card-width: 190px;
  flex: none;
}
.pick {
  flex: 1;
  min-width: 200px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-2);
  margin-bottom: var(--em-space-2);
  font-size: 12px;
  font-weight: 600;
  color: var(--em-muted);
}
.field select {
  min-height: var(--em-target);
  padding: 10px 12px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-bg);
  font: inherit;
  font-size: 14px;
}
.resting {
  margin: var(--em-space-4) 0 0;
  padding: 0;
  list-style: none;
}
.resting li {
  padding: 14px 16px;
  border: 1px dashed var(--em-border);
  font-size: 14px;
  color: var(--em-muted);
}
.label {
  margin: var(--em-space-4) 0 var(--em-space-2);
  font-size: 12px;
  font-weight: 600;
  color: var(--em-muted);
}
.wide {
  display: flex;
}
.wide :deep(.tab) {
  flex: 1;
}
.start-form .caption {
  margin: var(--em-space-2) 0 var(--em-space-3);
}
@media (max-width: 700px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--em-space-4);
  }
  .look {
    padding: 32px 16px;
  }
  .wild-card {
    --card-width: 170px;
    margin: 0 auto;
  }
  .buttons > * {
    flex: 1;
  }
}
</style>
