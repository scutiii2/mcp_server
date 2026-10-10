<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { emberlingsClient, type PersonalityItem } from "../../api/EmberlingsClient";
import { useEmberlingsStore } from "../../stores/emberlings";
import { errorMessage } from "../../utils/errors";
import { titleCase } from "../../utils/emberlings";
import SegmentedControl from "../SegmentedControl.vue";
import ToggleSwitch from "../ToggleSwitch.vue";

/** A Spark's five presets: up to three personality instances each. An
 * autonomous Spark lets one of them lead each round. */
const props = defineProps<{ sparkId: string; personalities: PersonalityItem[] }>();
const store = useEmberlingsStore();

const MAX_EQUIPPED = 3;
const SLOT_OPTIONS = [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `Preset ${n}` }));

const slot = ref("1");
const chosen = ref<string[]>([]);
const saved = ref<string[]>([]);
const loading = ref(false);
const loadError = ref("");
const dirty = computed(() => chosen.value.join(",") !== saved.value.join(","));

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
  const preset = await store.savePreset(props.sparkId, Number(slot.value), chosen.value);
  if (preset) {
    saved.value = preset.instance_ids;
    chosen.value = [...preset.instance_ids];
  }
}
</script>

<template>
  <section class="preset-editor">
    <h4>Presets</h4>
    <SegmentedControl v-model="slot" :options="SLOT_OPTIONS" aria-label="Preset slot" />
    <p class="muted hint">Up to {{ MAX_EQUIPPED }} personalities. An autonomous Spark lets one of them lead each round.</p>
    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-else-if="loading" class="muted">Loading …</p>
    <p v-else-if="personalities.length === 0" class="muted">This Spark has no personalities yet.</p>
    <ul v-else class="choices">
      <li v-for="p in personalities" :key="p.id">
        <ToggleSwitch
          small
          :checked="chosen.includes(p.id)"
          :disabled="!chosen.includes(p.id) && chosen.length >= MAX_EQUIPPED"
          @change="toggle(p.id, ($event.target as HTMLInputElement).checked)"
        >
          {{ titleCase(p.type) }} · tier {{ p.tier }}
        </ToggleSwitch>
      </li>
    </ul>
    <button type="button" class="primary" :disabled="!dirty || store.busy" @click="save">Save preset</button>
  </section>
</template>

<style scoped>
.preset-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
}
h4 {
  margin: 0;
}
.hint {
  margin: 0;
  font-size: 0.85em;
}
.choices {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.primary {
  align-self: flex-start;
}
</style>
