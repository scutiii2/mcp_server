<script setup lang="ts">
import { computed, reactive } from "vue";
import type { PendingQuestion, QuestionAnswer } from "../api/types";

/** The clickable questions the agent asks mid-answer. One card per question
 * set: every question has its options as pills and an "Other" typed answer;
 * Submit needs every question answered, Skip declines all of them. The agent
 * confirms with a question_resolved event, which removes the card. */

const props = defineProps<{ pending: PendingQuestion; answering: boolean }>();
const emit = defineEmits<{
  answer: [stepId: string, answers: QuestionAnswer[]];
  skip: [stepId: string];
}>();

interface Choice {
  selected: string[];
  otherOn: boolean;
  otherText: string;
}

const choices = reactive<Choice[]>(props.pending.questions.map(() => ({ selected: [], otherOn: false, otherText: "" })));

function toggle(index: number, label: string): void {
  const choice = choices[index]!;
  const question = props.pending.questions[index]!;
  if (choice.selected.includes(label)) {
    choice.selected = choice.selected.filter((l) => l !== label);
  } else if (question.multi_select) {
    choice.selected = [...choice.selected, label];
  } else {
    choice.selected = [label];
    choice.otherOn = false;
  }
}

function toggleOther(index: number): void {
  const choice = choices[index]!;
  choice.otherOn = !choice.otherOn;
  if (choice.otherOn && !props.pending.questions[index]!.multi_select) choice.selected = [];
}

const complete = computed(() =>
  choices.every((c) => c.selected.length > 0 || (c.otherOn && c.otherText.trim() !== "")),
);

function submit(): void {
  if (!complete.value || props.answering) return;
  emit(
    "answer",
    props.pending.id,
    choices.map((c) => ({
      selected: [...c.selected],
      other: c.otherOn && c.otherText.trim() !== "" ? c.otherText.trim() : null,
    })),
  );
}
</script>

<template>
  <form class="question-card" aria-label="The agent has a question" @submit.prevent="submit">
    <section v-for="(q, i) in pending.questions" :key="i" class="q">
      <header>
        <span class="chip">{{ q.header }}</span>
        <span v-if="q.multi_select" class="hint">choose any</span>
      </header>
      <p class="text">{{ q.question }}</p>
      <div class="options" role="group" :aria-label="q.question">
        <button
          v-for="o in q.options"
          :key="o.label"
          type="button"
          class="opt"
          :aria-pressed="choices[i]!.selected.includes(o.label)"
          :disabled="answering"
          @click="toggle(i, o.label)"
        >
          <span class="label">{{ o.label }}</span>
          <span v-if="o.description" class="desc">{{ o.description }}</span>
        </button>
        <button
          type="button"
          class="opt"
          :aria-pressed="choices[i]!.otherOn"
          :disabled="answering"
          @click="toggleOther(i)"
        >
          <span class="label">Other</span>
        </button>
      </div>
      <input
        v-if="choices[i]!.otherOn"
        v-model="choices[i]!.otherText"
        type="text"
        class="other"
        maxlength="500"
        placeholder="Type your own answer"
        :aria-label="`Your own answer to: ${q.question}`"
        :disabled="answering"
      />
    </section>
    <div class="buttons">
      <button type="submit" class="submit" :disabled="!complete || answering">Submit</button>
      <button type="button" class="skip" :disabled="answering" @click="emit('skip', pending.id)">Skip</button>
    </div>
    <p class="note">The agent waits for you. Skip lets it go on with its best guess.</p>
  </form>
</template>

<style scoped>
.question-card {
  display: grid;
  gap: 14px;
  padding: 10px 12px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
.q {
  display: grid;
  gap: 6px;
}
header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chip {
  padding: 1px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
}
.hint {
  font-size: 0.75em;
  color: var(--muted);
}
.text {
  margin: 0;
  font-size: 0.95em;
  overflow-wrap: anywhere;
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.opt {
  display: grid;
  gap: 2px;
  max-width: 100%;
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  text-align: left;
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.opt:hover:not(:disabled) {
  border-color: var(--accent);
}
.opt[aria-pressed="true"] {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.opt .desc {
  font-size: 0.85em;
  opacity: 0.8;
  overflow-wrap: anywhere;
}
.other {
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font: inherit;
  font-size: 0.9em;
  color: var(--text);
  background: var(--bg);
}
.other:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.buttons button {
  padding: 5px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.buttons .submit {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.buttons button:disabled,
.opt:disabled {
  cursor: default;
  opacity: 0.45;
}
.note {
  margin: 0;
  font-size: 0.75em;
  color: var(--muted);
}
</style>
