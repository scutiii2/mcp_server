<script setup lang="ts">
import { computed, ref } from "vue";
import { emberlingsClient, type OwnedSpark, type PersonalityItem } from "../../api/EmberlingsClient";
import cardBackUrl from "../../assets/emberlings/card_back.png";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { filterByType, groupByType, typeLabel, typesPresent } from "../../utils/ascensionTypes";
import { titleCase } from "../../utils/emberlings";
import PresetEditor from "./PresetEditor.vue";
import SparkCard from "./SparkCard.vue";
import SparkTemplateCard from "./SparkTemplateCard.vue";
import EmBar from "./ui/EmBar.vue";
import EmDialog from "./ui/EmDialog.vue";
import EmNotice from "./ui/EmNotice.vue";
import EmSwitch from "./ui/EmSwitch.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";

/** The Collection tab: owned Sparks as small cards with a caption, the rest of the
 * catalog as face-down cards, and a card's details (the full card, personalities,
 * presets) in a dialog. */
const store = useEmberlingsStore();
const PAGE_SIZE = 50;

const typeFilter = ref<string | null>(null);
const grouped = ref(false);
const allOwned = computed(() => store.profile?.sparks ?? []);
const allNotOwned = computed(() => {
  const ids = new Set(allOwned.value.map((s) => s.spark_id));
  return (store.catalog?.sparks ?? []).filter((s) => !ids.has(s.id));
});
/** The types to offer as filters: those any Ascended in the catalog has. */
const types = computed(() => typesPresent(store.catalog?.sparks ?? []));
const owned = computed(() => filterByType(allOwned.value, typeFilter.value));
const notOwned = computed(() => filterByType(allNotOwned.value, typeFilter.value));
const groups = computed(() => groupByType(owned.value));

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
    <div v-if="types.length" class="filters">
      <div class="chips" role="group" aria-label="Filter by Ascension Type">
        <button type="button" class="chip" :aria-pressed="typeFilter === null" @click="typeFilter = null">All</button>
        <button
          v-for="id in types"
          :key="id"
          type="button"
          class="chip"
          :aria-pressed="typeFilter === id"
          @click="typeFilter = typeFilter === id ? null : id"
        >
          {{ typeLabel(id) }}
        </button>
      </div>
      <EmSwitch v-model="grouped" label="Group by type" />
    </div>

    <div class="section-head">
      <h3 class="em-pixel">Collected Sparks</h3>
      <small>Choose a card to manage presets</small>
    </div>
    <template v-if="grouped">
      <section v-for="group in groups" :key="group.typeId ?? 'none'" class="group" :data-type="group.typeId ?? 'none'">
        <h4 class="group-name">{{ group.label }} <small class="em-num">{{ group.items.length }}</small></h4>
        <div class="grid">
          <SparkCard v-for="spark in group.items" :key="spark.spark_id" :spark="spark" @open="show(spark)" />
        </div>
      </section>
    </template>
    <div v-else class="grid">
      <SparkCard v-for="spark in owned" :key="spark.spark_id" :spark="spark" @open="show(spark)" />
    </div>
    <p v-if="owned.length === 0" class="empty">{{ typeFilter === null ? "None collected yet." : `No ${typeLabel(typeFilter)} Sparks collected yet.` }}</p>

    <template v-if="notOwned.length">
      <div class="section-head">
        <h3 class="em-pixel">Not collected yet</h3>
        <small>{{ notOwned.length }} still to find</small>
      </div>
      <ul class="grid missing">
        <li v-for="spark in notOwned" :key="spark.id" class="missing-spark">
          <img class="back" :src="cardBackUrl" alt="" draggable="false" />
          <h4 class="missing-name">{{ spark.name }}</h4>
          <p class="hint">{{ spark.forbidden ? "Only by capture" : "Catch one, or buy copies in the shop" }}</p>
        </li>
      </ul>
    </template>

    <EmDialog :open="open !== null" title="Spark details" wide @close="open = null">
      <div v-if="open" class="details">
        <SparkTemplateCard v-if="openInfo" class="big-card" :spark="openInfo" :level="open.level" :tier-id="open.tier_id" />
        <div class="side">
          <h3 class="em-pixel name">{{ open.name }}</h3>
          <p class="level em-num">Level {{ open.level }} of {{ open.level_cap }}</p>
          <div class="badges">
            <EmTierBadge :tier-id="open.tier_id" />
            <span v-for="id in open.ascension_types" :key="id" class="type-chip">{{ typeLabel(id) }}</span>
          </div>
          <div class="xp">
            <template v-if="open.xp_needed !== null">
              <EmBar :value="open.xp" :max="open.xp_needed" :label="`${open.name} XP`" />
              <span class="em-num">{{ open.xp }} / {{ open.xp_needed }} XP</span>
            </template>
            <span v-else>Highest level reached</span>
          </div>

          <div class="people-head">
            <h4>Collected personalities</h4>
            <small class="em-num">{{ personalities.length }}{{ nextCursor !== null ? "+" : "" }} collected</small>
          </div>
          <EmNotice v-if="detailError" tone="error">{{ detailError }}</EmNotice>
          <ul v-if="personalities.length" class="personalities">
            <li v-for="p in personalities" :key="p.id">
              <strong>{{ titleCase(p.type) }}</strong>
              <EmTierBadge tier-id="common" :label="`Tier ${p.tier}`" />
            </li>
          </ul>
          <p v-else-if="!loadingMore" class="muted">None collected yet.</p>
          <button v-if="nextCursor !== null" type="button" class="more" :disabled="loadingMore" @click="loadPersonalities(nextCursor)">
            Show more
          </button>

          <PresetEditor :spark-id="open.spark_id" :spark-name="open.name" :personalities="personalities" />
        </div>
      </div>
    </EmDialog>
  </section>
</template>

<style scoped>
.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-3);
  margin: var(--em-space-6) 0 var(--em-space-4);
}
.section-head:first-child {
  margin-top: 0;
}
.section-head h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.4;
}
.section-head small {
  color: var(--em-muted);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 24px 20px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.empty {
  color: var(--em-muted);
}
.missing-spark {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.back {
  width: 100%;
  margin-bottom: 6px;
  border-radius: var(--em-radius);
  filter: grayscale(0.4);
  opacity: 0.7;
  user-select: none;
}
.missing-name {
  margin: 0;
  font-size: 16px;
}
.hint {
  font-size: 12px;
  color: var(--em-muted);
}
.details {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-6);
}
.big-card {
  flex: none;
}
.side {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--em-space-2);
  min-width: 280px;
}
.name {
  margin: 0;
  font-size: 18px;
  line-height: 1.4;
}
.level {
  color: var(--em-muted);
}
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-2);
  align-items: center;
}
.type-chip {
  padding: 2px 8px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-muted);
  font-size: 12px;
  font-weight: 600;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-3);
  margin-bottom: var(--em-space-4);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--em-space-2);
}
.chip {
  min-height: var(--em-target);
  padding: 0 14px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-panel);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.chip[aria-pressed="true"] {
  border-color: var(--em-accent);
  color: var(--em-on-accent);
  background: var(--em-accent);
}
.group {
  margin-bottom: var(--em-space-5);
}
.group-name {
  margin: 0 0 var(--em-space-3);
  font-size: 16px;
}
.group-name small {
  margin-left: var(--em-space-2);
  color: var(--em-muted);
}
.xp {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: var(--em-space-2) 0 var(--em-space-3);
  font-size: 12px;
  color: var(--em-muted);
}
.people-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--em-space-3);
  margin-top: var(--em-space-3);
}
.people-head h4 {
  margin: 0;
  font-size: 16px;
}
.people-head small {
  color: var(--em-muted);
}
.personalities {
  margin: 0;
  padding: 0;
  list-style: none;
}
.personalities li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-3);
  padding: 12px 0;
  border-bottom: 1px solid var(--em-divider);
  font-size: 13px;
}
.more {
  align-self: flex-start;
  min-height: var(--em-target);
  padding: 0 4px;
  border: 0;
  color: var(--em-accent);
  background: none;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
@media (max-width: 700px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px 18px;
  }
  .big-card {
    --card-width: 100%;
    max-width: 440px;
    margin: 0 auto;
  }
}
</style>
