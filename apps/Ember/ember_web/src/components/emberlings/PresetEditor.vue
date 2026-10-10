<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { emberlingsClient, type PersonalityItem } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { titleCase } from "../../utils/emberlings";
import EmButton from "./ui/EmButton.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmNotice from "./ui/EmNotice.vue";
import EmSwitch from "./ui/EmSwitch.vue";
import EmTabs from "./ui/EmTabs.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";
import EmToast from "./ui/EmToast.vue";

/** A Spark's five presets: up to three personality instances each. An autonomous Spark
 * lets one of them lead each round. */
const props = defineProps<{ sparkId: string; sparkName: string; personalities: PersonalityItem[] }>();
const store = useEmberlingsStore();

const MAX_EQUIPPED = 3;
const SLOT_OPTIONS = [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }));

const slot = ref("1");
const chosen = ref<string[]>([]);
const saved = ref<string[]>([]);
const loading = ref(false);
const loadError = ref("");
const toastOpen = ref(false);
const toastMessage = ref("");
const dirty = computed(() => chosen.value.join(",") !== saved.value.join(","));
const full = computed(() => chosen.value.length >= MAX_EQUIPPED);

async function load(): Promise<void> {
  const sparkId = props.sparkId;
  const wanted = slot.value;
  loading.value = true;
  loadError.value = "";
  try {
    const preset = await emberlingsClient.preset(sparkId, Number(wanted));
    if (sparkId !== props.sparkId || wanted !== slot.value) return;
    saved.value = preset.instance_ids;
    chosen.value = [...preset.instance_ids];
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

watch([() => props.sparkId, slot], () => void load(), { immediate: true });

function toggle(id: string, on: boolean): void {
  if (on && !chosen.value.includes(id) && chosen.value.length < MAX_EQUIPPED) chosen.value = [...chosen.value, id];
  else if (!on) chosen.value = chosen.value.filter((c) => c !== id);
}

async function save(): Promise<void> {
  const slotNumber = Number(slot.value);
  const preset = await store.savePreset(props.sparkId, slotNumber, chosen.value);
  if (preset) {
    saved.value = preset.instance_ids;
    chosen.value = [...preset.instance_ids];
    toastMessage.value = `Preset ${slotNumber} saved. ${props.sparkName} is ready.`;
    toastOpen.value = true;
  }
}
</script>

<template>
  <section class="preset-editor">
    <h4 class="heading">Personality presets</h4>
    <EmTabs v-model="slot" class="slots" :options="SLOT_OPTIONS" aria-label="Preset slot" />
    <p class="count em-num">Preset {{ slot }} · {{ chosen.length }} of {{ MAX_EQUIPPED }} personalities equipped</p>

    <EmNotice v-if="loadError" tone="error">{{ loadError }}</EmNotice>
    <p v-else-if="loading" class="muted">Loading …</p>
    <p v-else-if="personalities.length === 0" class="muted">This Spark has no personalities yet.</p>
    <ul v-else class="choices">
      <li v-for="p in personalities" :key="p.id">
        <EmSwitch :model-value="chosen.includes(p.id)" :label="titleCase(p.type)" :disabled="!chosen.includes(p.id) && full" @update:model-value="toggle(p.id, $event)">
          <EmTierBadge tier-id="common" :label="`Tier ${p.tier}`" class="badge" />
        </EmSwitch>
      </li>
    </ul>

    <p class="hint">Equip up to {{ MAX_EQUIPPED }} collected personalities per preset. An autonomous Spark lets one of them lead each round.</p>
    <EmButton variant="primary" class="save" :disabled="!dirty || store.busy" @click="save"><EmIcon name="check" /> Save preset</EmButton>
    <EmToast :open="toastOpen" :message="toastMessage" @close="toastOpen = false" />
  </section>
</template>

<style scoped>
.preset-editor {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-3);
  margin-top: var(--em-space-5);
}
.heading {
  margin: 0;
  font-size: 16px;
}
.slots {
  display: flex;
}
.slots :deep(.tab) {
  flex: 1;
}
.count {
  font-size: 12px;
  color: var(--em-muted);
}
.choices {
  margin: 0;
  padding: 0;
  list-style: none;
}
.choices li {
  border-bottom: 1px solid var(--em-divider);
}
.badge {
  margin-left: auto;
}
.hint {
  padding: 10px 14px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  background: var(--em-bg);
  font-size: 12px;
  color: var(--em-muted);
}
.save {
  width: 100%;
}
</style>
