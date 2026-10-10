<script setup lang="ts">
import { computed, ref } from "vue";
import { emberlingsClient, type OwnedSpark, type PersonalityItem } from "../../api/EmberlingsClient";
import cardBackUrl from "../../assets/emberlings/card_back.png";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { titleCase } from "../../utils/emberlings";
import BaseModal from "../BaseModal.vue";
import PresetEditor from "./PresetEditor.vue";
import SparkCard from "./SparkCard.vue";
import SparkTemplateCard from "./SparkTemplateCard.vue";
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
const openInfo = computed(() => store.catalog?.sparks.find((s) => s.id === open.value?.spark_id) ?? null);
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
          <img class="back" :src="cardBackUrl" alt="" draggable="false" />
          <span class="missing-name">{{ spark.name }}</span>
          <span class="muted">{{ spark.forbidden ? "Only by capture" : "Catch one, or buy copies in the shop" }}</span>
        </li>
      </ul>
    </template>

    <BaseModal :open="open !== null" :title="open?.name ?? ''" wide @close="open = null">
      <div v-if="open" class="details">
        <SparkTemplateCard v-if="openInfo" class="big-card" :spark="openInfo" :level="open.level" :tier-id="open.tier_id" />
        <div class="side">
          <p class="muted level">Level {{ open.level }} of {{ open.level_cap }} <TierBadge :tier-id="open.tier_id" /></p>

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
  grid-template-columns: repeat(auto-fill, 180px);
  gap: 20px 16px;
}
.missing {
  display: grid;
  grid-template-columns: repeat(auto-fill, 180px);
  gap: 20px 16px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.missing-spark {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 180px;
}
.back {
  width: 100%;
  margin-bottom: 4px;
  border-radius: var(--radius-lg);
  filter: grayscale(0.6);
  opacity: 0.55;
  user-select: none;
}
.missing-name {
  font-weight: 600;
}
.details {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
}
.big-card {
  flex: none;
}
.side {
  flex: 1;
  min-width: 240px;
}
.details h4 {
  margin: 14px 0 6px;
}
.level {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}
.personalities {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
