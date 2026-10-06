<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { commandsClient, type ParamOption } from "../api/CommandsClient";
import type { JsonSchema } from "../api/types";
import { errorMessage } from "../utils/errors";
import { buildArgs, fieldsFromSchema, initialValues, type FieldValues, type ToolField } from "../utils/toolSchema";

/** A form for one tool's parameters, from its JSON Schema (Tools page and
 * the chat's command form). Follows chat_app's command-form hints: selects
 * filled from mcp_server (`options_url`, optionally depending on another
 * field), options that fill in (`sets`) or show (`shows`) other values, and
 * file fields that upload the chosen file and hold its server-side path. */

const props = withDefaults(defineProps<{ schema: JsonSchema; running: boolean; submitLabel?: string; live?: boolean }>(), {
  submitLabel: "Run",
  live: false,
});
const emit = defineEmits<{ run: [args: Record<string, unknown>] }>();

const fields = computed(() => fieldsFromSchema(props.schema));
const values = ref<FieldValues>(initialValues(fields.value));
const errors = ref<Record<string, string>>({});

// --- selects filled from mcp_server ------------------------------------------

interface RemoteOptions {
  state: "loading" | "ready" | "failed" | "waiting";
  options: ParamOption[];
  error: string;
}
const remote = reactive<Record<string, RemoteOptions>>({});

async function loadOptions(field: ToolField): Promise<void> {
  if (!field.optionsUrl) return;
  const args: Record<string, string> = {};
  if (field.dependsOn) {
    const parent = values.value[field.dependsOn];
    if (typeof parent !== "string" || parent === "") {
      remote[field.name] = { state: "waiting", options: [], error: "" };
      return;
    }
    args[field.dependsOn] = parent;
  }
  remote[field.name] = { state: "loading", options: [], error: "" };
  try {
    const options = await commandsClient.options(field.optionsUrl, args);
    remote[field.name] = { state: "ready", options, error: "" };
  } catch (err) {
    // Like chat_app: the field falls back to a plain text box.
    remote[field.name] = { state: "failed", options: [], error: errorMessage(err) };
  }
}

onMounted(() => {
  for (const f of fields.value) if (f.optionsUrl) void loadOptions(f);
});

// A dependent select reloads (and clears) when the field it depends on changes.
watch(
  () => fields.value.filter((f) => f.optionsUrl && f.dependsOn).map((f) => values.value[f.dependsOn!]),
  (now, before) => {
    fields.value
      .filter((f) => f.optionsUrl && f.dependsOn)
      .forEach((f, i) => {
        if (before && now[i] === before[i]) return;
        values.value[f.name] = "";
        void loadOptions(f);
      });
  },
);

/** The choices of a select field, or null when it's drawn as a text box. */
function choicesOf(field: ToolField): { value: string; label: string }[] | null {
  if (field.optionsUrl) {
    const r = remote[field.name];
    return r && r.state !== "failed" ? r.options : null;
  }
  if (field.options.length) return field.options.map((o) => ({ value: o, label: o }));
  if (field.widget === "select" && field.examples.length) return field.examples.map((o) => ({ value: o, label: o }));
  return null;
}

function chosenOption(field: ToolField): ParamOption | undefined {
  const value = values.value[field.name];
  return remote[field.name]?.options.find((o) => o.value === value);
}

function optionField(option: ParamOption, key: string): string | undefined {
  if (key === "value") return option.value;
  if (key === "label") return option.label;
  return option.extra[key];
}

function onSelect(field: ToolField): void {
  const option = chosenOption(field);
  if (!option) return;
  for (const [param, key] of Object.entries(field.sets)) {
    const value = optionField(option, key);
    if (value !== undefined && param in values.value) values.value[param] = value;
  }
}

function shownLines(field: ToolField): { label: string; value: string }[] {
  const option = chosenOption(field);
  if (!option) return [];
  return Object.entries(field.shows)
    .map(([label, key]) => ({ label, value: optionField(option, key) ?? "" }))
    .filter((line) => line.value !== "");
}

// --- file fields --------------------------------------------------------------

interface Upload {
  filename: string;
  state: "uploading" | "done" | "failed";
  error: string;
}
const uploads = reactive<Record<string, Upload>>({});
const dragging = ref<string | null>(null);
const uploading = computed(() => Object.values(uploads).some((u) => u.state === "uploading"));

async function upload(field: ToolField, file: File | undefined): Promise<void> {
  if (!file) return;
  uploads[field.name] = { filename: file.name, state: "uploading", error: "" };
  values.value[field.name] = "";
  try {
    const path = await commandsClient.upload(file);
    if (uploads[field.name]?.filename !== file.name) return; // replaced meanwhile
    values.value[field.name] = path;
    uploads[field.name] = { filename: file.name, state: "done", error: "" };
  } catch (err) {
    uploads[field.name] = { filename: file.name, state: "failed", error: errorMessage(err) };
  }
}

function onFileInput(field: ToolField, event: Event): void {
  const input = event.target as HTMLInputElement;
  void upload(field, input.files?.[0]);
  input.value = "";
}

function onDrop(field: ToolField, event: DragEvent): void {
  dragging.value = null;
  void upload(field, event.dataTransfer?.files[0]);
}

// --- submit -------------------------------------------------------------------

function submit(): void {
  if (uploading.value) return;
  const built = buildArgs(fields.value, values.value);
  if (!built.ok) {
    errors.value = built.errors;
    return;
  }
  errors.value = {};
  emit("run", built.args);
}

/** Live mode: a committed change (the native `change` event: slider release,
 * toggle, select, text on blur) runs the tool again. */
function onFormChange(): void {
  if (props.live) submit();
}
// Live mode also runs once as it opens, with the defaults.
onMounted(() => {
  if (props.live) submit();
});

function inputType(field: ToolField): string {
  switch (field.widget) {
    case "number":
    case "range":
    case "date":
    case "password":
      return field.widget;
    default:
      return "text";
  }
}
</script>

<template>
  <form :class="['tool-form', { live }]" @submit.prevent="submit" @change="onFormChange">
    <p v-if="fields.length === 0" class="muted">This tool takes no parameters.</p>

    <div v-for="f in fields" :key="f.name" :class="['field', { invalid: errors[f.name] }]">
      <label v-if="f.widget === 'checkbox'" class="check">
        <input v-model="values[f.name]" type="checkbox" />
        <span>{{ f.label }}</span>
      </label>
      <template v-else>
        <label :for="`field-${f.name}`">
          {{ f.label }}<span v-if="f.required" class="req" title="Required">*</span>
          <code class="name">{{ f.name }}</code>
        </label>

        <!-- File: uploaded to mcp_server; the field holds the path it got there. -->
        <div
          v-if="f.widget === 'file'"
          :class="['drop', { over: dragging === f.name }]"
          @dragover.prevent="dragging = f.name"
          @dragleave="dragging = null"
          @drop.prevent="onDrop(f, $event)"
        >
          <input :id="`field-${f.name}`" type="file" class="file-input" @change="onFileInput(f, $event)" />
          <span v-if="!uploads[f.name]" class="muted">Drop a file here or choose one</span>
          <span v-else-if="uploads[f.name]!.state === 'uploading'" class="muted">uploading {{ uploads[f.name]!.filename }} ...</span>
          <span v-else-if="uploads[f.name]!.state === 'done'">✓ {{ uploads[f.name]!.filename }}</span>
          <span v-else class="error">{{ uploads[f.name]!.filename }}: {{ uploads[f.name]!.error }}</span>
        </div>

        <template v-else-if="choicesOf(f) !== null">
          <select :id="`field-${f.name}`" v-model="values[f.name]" :disabled="remote[f.name]?.state === 'loading' || remote[f.name]?.state === 'waiting'" @change="onSelect(f)">
            <option value="">
              {{
                remote[f.name]?.state === "loading"
                  ? "loading ..."
                  : remote[f.name]?.state === "waiting"
                    ? `choose ${f.dependsOn} first`
                    : f.required
                      ? "(choose)"
                      : "(default)"
              }}
            </option>
            <option v-for="o in choicesOf(f)" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <dl v-if="shownLines(f).length" class="shows">
            <template v-for="line in shownLines(f)" :key="line.label">
              <dt>{{ line.label }}</dt>
              <dd>{{ line.value }}</dd>
            </template>
          </dl>
        </template>

        <textarea
          v-else-if="f.widget === 'json' || f.widget === 'textarea'"
          :id="`field-${f.name}`"
          v-model="values[f.name] as string"
          rows="4"
          spellcheck="false"
          :maxlength="f.maxLength"
          :placeholder="f.widget === 'json' ? 'JSON' : ''"
        />
        <div v-else-if="f.widget === 'range'" class="range-row">
          <input
            :id="`field-${f.name}`"
            v-model="values[f.name] as string"
            type="range"
            :step="f.step ?? 1"
            :min="f.min"
            :max="f.max"
          />
          <output v-if="live" class="readout" :for="`field-${f.name}`">{{ values[f.name] }}</output>
        </div>
        <input
          v-else
          :id="`field-${f.name}`"
          v-model="values[f.name] as string"
          :type="inputType(f)"
          :step="f.step ?? (f.kind === 'integer' ? 1 : 'any')"
          :min="f.min"
          :max="f.max"
          :maxlength="f.maxLength"
          :list="f.examples.length ? `examples-${f.name}` : undefined"
          :autocomplete="f.widget === 'password' ? 'off' : undefined"
        />
        <datalist v-if="f.examples.length" :id="`examples-${f.name}`">
          <option v-for="e in f.examples" :key="e" :value="e" />
        </datalist>
      </template>
      <small v-if="errors[f.name]" class="error">{{ errors[f.name] }}</small>
      <small v-else-if="remote[f.name]?.state === 'failed'" class="hint">
        Couldn't load the choices ({{ remote[f.name]!.error }}) - type the value instead.
      </small>
      <small v-else-if="f.description" class="hint">{{ f.description }}</small>
    </div>

    <button v-if="!live" type="submit" class="run" :disabled="running || uploading">
      {{ running ? "Running ..." : uploading ? "Uploading ..." : submitLabel }}
    </button>
  </form>
</template>

<style scoped>
.tool-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
label {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-weight: 600;
  font-size: 0.9em;
}
.check {
  font-weight: normal;
  font-size: 1em;
}
.req {
  color: var(--accent);
}
.name {
  font-family: var(--mono);
  font-weight: normal;
  font-size: 0.85em;
  color: var(--muted);
}
input:not([type="checkbox"]):not([type="file"]),
select,
textarea {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
}
input[type="range"] {
  padding: 0;
}
textarea {
  font-family: var(--mono);
  font-size: 0.9em;
  resize: vertical;
}
input:focus,
select:focus,
textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.invalid input,
.invalid select,
.invalid textarea,
.invalid .drop {
  border-color: var(--danger);
}
.drop {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  font-size: 0.9em;
}
.drop.over {
  border-color: var(--accent);
  background: var(--surface);
}
.shows {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 10px;
  margin: 2px 0 0;
  font-size: 0.85em;
}
.shows dt {
  color: var(--muted);
}
.shows dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.hint,
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
.run {
  align-self: flex-start;
  padding: 7px 18px;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.run:disabled {
  cursor: default;
  opacity: 0.5;
}
.range-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.range-row input[type="range"] {
  flex: 1;
  accent-color: var(--accent);
}
.readout {
  min-width: 2.5em;
  text-align: right;
  font-weight: 600;
}
/* Live forms: toggles are chips in a row, other controls take the full width. */
.live {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
}
.live .field {
  flex: 1 1 100%;
}
.live .field:has(> .check) {
  flex: 0 0 auto;
}
.live .check {
  position: relative;
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.9em;
}
.live .check input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.live .check:has(input:checked) {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-contrast);
}
.live .check:has(input:focus-visible) {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
