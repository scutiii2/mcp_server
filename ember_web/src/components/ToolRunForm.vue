<script setup lang="ts">
import { computed, ref } from "vue";
import type { JsonSchema } from "../api/types";
import { buildArgs, fieldsFromSchema, initialValues, type FieldValues } from "../utils/toolSchema";

const props = defineProps<{ schema: JsonSchema; running: boolean }>();
const emit = defineEmits<{ run: [args: Record<string, unknown>] }>();

const fields = computed(() => fieldsFromSchema(props.schema));
const values = ref<FieldValues>(initialValues(fields.value));
const errors = ref<Record<string, string>>({});

function submit(): void {
  const built = buildArgs(fields.value, values.value);
  if (!built.ok) {
    errors.value = built.errors;
    return;
  }
  errors.value = {};
  emit("run", built.args);
}
</script>

<template>
  <form class="tool-form" @submit.prevent="submit">
    <p v-if="fields.length === 0" class="muted">This tool takes no parameters.</p>

    <div v-for="f in fields" :key="f.name" :class="['field', { invalid: errors[f.name] }]">
      <label v-if="f.kind === 'boolean'" class="check">
        <input v-model="values[f.name]" type="checkbox" />
        <span>{{ f.label }}</span>
      </label>
      <template v-else>
        <label :for="`field-${f.name}`">
          {{ f.label }}<span v-if="f.required" class="req" title="Required">*</span>
          <code class="name">{{ f.name }}</code>
        </label>
        <select v-if="f.kind === 'enum'" :id="`field-${f.name}`" v-model="values[f.name]">
          <option v-if="!f.required" value="">(default)</option>
          <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
        </select>
        <textarea
          v-else-if="f.kind === 'json'"
          :id="`field-${f.name}`"
          v-model="values[f.name] as string"
          rows="4"
          spellcheck="false"
          placeholder="JSON"
        />
        <input
          v-else
          :id="`field-${f.name}`"
          v-model="values[f.name] as string"
          :type="f.kind === 'string' ? 'text' : 'number'"
          :step="f.kind === 'integer' ? 1 : 'any'"
        />
      </template>
      <small v-if="errors[f.name]" class="error">{{ errors[f.name] }}</small>
      <small v-else-if="f.description" class="hint">{{ f.description }}</small>
    </div>

    <button type="submit" class="run" :disabled="running">{{ running ? "Running ..." : "Run" }}</button>
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
input:not([type="checkbox"]),
select,
textarea {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
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
.invalid textarea {
  border-color: var(--danger);
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
</style>
