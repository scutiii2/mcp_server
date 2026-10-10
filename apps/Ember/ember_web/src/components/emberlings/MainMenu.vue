<script setup lang="ts">
import { computed, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "../ConfirmModal.vue";

/** The Emberlings main menu, the first screen. Without a save it offers New
 * game; with one it offers Continue, Quick battle and Shop. Reset progress
 * lives here, behind a type-to-confirm. */
export type PlayTarget = "collection" | "battle" | "shop";
const emit = defineEmits<{ newGame: []; play: [target: PlayTarget] }>();

const store = useEmberlingsStore();
const hasSave = computed(() => store.profile !== null);
const inBattle = computed(() => store.profile?.active_battle != null || store.battle?.status === "active");
const confirmingReset = ref(false);
const showingHelp = ref(false);

async function reset(): Promise<void> {
  if (await store.resetProgress()) confirmingReset.value = false;
}
</script>

<template>
  <section class="menu">
    <header class="hero">
      <h2 class="page-title">Emberlings</h2>
      <p class="muted">{{ hasSave ? "Welcome back" : "Collect Sparks. Battle wild ones." }}</p>
    </header>

    <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>

    <nav class="buttons" aria-label="Main menu">
      <template v-if="hasSave">
        <button type="button" class="primary" @click="emit('play', 'collection')">Continue</button>
        <button type="button" @click="emit('play', 'battle')">Quick battle</button>
        <button type="button" @click="emit('play', 'shop')">Shop</button>
      </template>
      <button v-else type="button" class="primary" @click="emit('newGame')">New game</button>
      <button type="button" @click="showingHelp = true">How to play</button>
      <button v-if="hasSave" type="button" class="danger" :disabled="inBattle" @click="confirmingReset = true">
        Reset progress
      </button>
    </nav>

    <p v-if="hasSave && inBattle" class="muted note">Finish or forfeit your battle to reset</p>
    <p v-if="hasSave" class="muted stats">
      <span>{{ store.profile?.sparks.length }} Sparks</span>
      <span>{{ store.profile?.insignia }} Insignia</span>
    </p>
    <p v-else class="muted stats">No save found for this account</p>

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

    <BaseModal :open="showingHelp" title="How to play" @close="showingHelp = false">
      <ul class="help">
        <li>Pick a first Spark. It stays yours.</li>
        <li>Battle wild Sparks to win Insignia and catch new ones.</li>
        <li>In a manual battle, choose each action. In autonomous mode your Spark acts on its own.</li>
        <li>An EMBLEM prompt gives you 5 seconds to answer.</li>
        <li>Spend Insignia in the shop.</li>
      </ul>
    </BaseModal>
  </section>
</template>

<style scoped>
.menu {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 0;
}
.hero {
  text-align: center;
}
.hero p {
  margin: 4px 0 0;
}
.buttons {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 260px;
  margin-top: 20px;
}
.buttons button {
  height: 40px;
}
.danger {
  color: var(--danger);
  border-color: var(--danger);
}
.danger:disabled {
  opacity: 0.5;
}
.note,
.stats {
  margin: 10px 0 0;
  font-size: 0.85em;
}
.stats {
  display: flex;
  gap: 16px;
}
.help {
  margin: 0;
  padding-left: 18px;
  line-height: 1.6;
}
</style>
