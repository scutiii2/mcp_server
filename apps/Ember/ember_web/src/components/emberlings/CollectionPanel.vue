<script setup lang="ts">
import { computed, ref } from "vue";
import { emberlingsClient, type OwnedSpark, type PersonalityItem } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "../ConfirmModal.vue";
import PresetEditor from "./PresetEditor.vue";
import SparkCard from "./SparkCard.vue";
import TierBadge from "./TierBadge.vue";

/** The Collection tab: owned Sparks as cards, the rest of the catalog greyed
 * out, and a card's details (abilities, personalities, presets) in a dialog. */
const store = useEmberlingsStore();
const PAGE_SIZE = 50;

const owned = computed(() => store.profile?.sparks ?? []);
const notOwned = computed(() => {
  const ids = new Set(owned.value.map((s) => s.spark_id));
  return (store.catalog?.sparks ?? []).filter((s) => !ids.has(s.id));
});

const open = ref<OwnedSpark | null>(null);
const abilities = computed(() => store.catalog?.sparks.find((s) => s.id === open.value?.spark_id)?.abilities ?? []);
const personalities = ref<PersonalityItem[]>([]);
const nextCursor = ref<number | null>(null);
const loadingMore = ref(false);
const detailError = ref("");

async function loadPersonalities(cursor: number | null): Promise<void> {
  const spark = open.value;
  if (spark === null) return;
  loadingMore.value = true;
  detailError.value = "";
  try {
    const page = await emberlingsClient.personalities(spark.spark_id, cursor, PAGE_SIZE);
    if (open.value?.spark_id !== spark.spark_id) return;
    personalities.value = cursor === null ? page.items : [...personalities.value, ...page.items];
    nextCursor.value = page.next_cursor;
  } catch (err) {
    detailError.value = errorMessage(err);
  } finally {
    loadingMore.value = false;
  }
}

const confirmingReset = ref(false);
const inBattle = computed(() => store.profile?.active_battle != null || store.battle?.status === "active");

async function reset(): Promise<void> {
  if (await store.resetProgress()) confirmingReset.value = false;
}

function show(spark: OwnedSpark): void {
  open.value = spark;
  personalities.value = [];
  nextCursor.value = null;
  void loadPersonalities(null);
}
</script>

<template>
  <section class="collection">
    <h3>Your Sparks</h3>
    <div class="grid">
      <SparkCard v-for="spark in owned" :key="spark.spark_id" :spark="spark" @open="show(spark)" />
    </div>

    <template v-if="notOwned.length">
      <h3>Not collected yet</h3>
      <ul class="missing">
        <li v-for="spark in notOwned" :key="spark.id" class="missing-spark">
          <span class="missing-name">{{ spark.name }}</span>
          <span class="muted">{{ spark.forbidden ? "Only by capture" : "Catch one, or buy copies in the shop" }}</span>
        </li>
      </ul>
    </template>

    <div v-if="store.profile" class="reset">
      <button type="button" class="reset-button" :disabled="inBattle" @click="confirmingReset = true">Reset progress</button>
      <p v-if="inBattle" class="muted">Finish or forfeit your battle first</p>
    </div>
    <ConfirmModal
      :open="confirmingReset"
      title="Reset all Emberlings progress?"
      message="Every Spark, personality, preset, EMBLEM and all Insignia are deleted. This cannot be undone."
      confirm-label="Reset progress"
      danger
      require-text="RESET"
      :busy="store.busy"
      @confirm="reset"
      @close="confirmingReset = false"
    />

    <BaseModal :open="open !== null" :title="open?.name ?? ''" @close="open = null">
      <div v-if="open" class="details">
        <p class="muted level">Level {{ open.level }} of {{ open.level_cap }} <TierBadge :tier-id="open.tier_id" /></p>

        <h4>Abilities</h4>
        <ul class="abilities">
          <li v-for="a in abilities" :key="a.id" :class="{ locked: a.unlock_level > open.level }">
            <span class="ability-name">{{ a.name }}</span>
            <span class="muted">{{ titleCase(a.category) }} · {{ a.percentage }}% · cooldown {{ a.cooldown }}</span>
            <span class="muted">
              {{ a.unlock_level > open.level ? `Unlocks at level ${a.unlock_level}` : `Unlocked at level ${a.unlock_level}` }}
            </span>
          </li>
        </ul>

        <h4>Personalities</h4>
        <p v-if="detailError" class="error">{{ detailError }}</p>
        <ul v-if="personalities.length" class="personalities">
          <li v-for="p in personalities" :key="p.id">{{ titleCase(p.type) }} · tier {{ p.tier }}</li>
        </ul>
        <p v-else-if="!loadingMore" class="muted">None collected yet.</p>
        <button v-if="nextCursor !== null" type="button" class="chip" :disabled="loadingMore" @click="loadPersonalities(nextCursor)">
          Show more
        </button>

        <PresetEditor :spark-id="open.spark_id" :personalities="personalities" />
      </div>
    </BaseModal>
  </section>
</template>

<style scoped>
.collection h3 {
  margin: 20px 0 10px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.missing {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.missing-spark {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  padding: 8px 12px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  opacity: 0.6;
}
.reset {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.reset p {
  margin: 0;
}
.reset-button {
  padding: 6px 14px;
  border: 1px solid var(--danger);
  border-radius: var(--radius-full);
  color: var(--danger);
  background: transparent;
  font: inherit;
  cursor: pointer;
}
.reset-button:disabled {
  cursor: default;
  opacity: 0.5;
}
.details h4 {
  margin: 14px 0 6px;
}
.level {
  display: flex;
  align-items: center;
  gap: 8px;
}
.abilities,
.personalities {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.abilities li {
  display: flex;
  flex-direction: column;
}
.abilities li.locked {
  opacity: 0.6;
}
.ability-name {
  font-weight: 600;
}
</style>
