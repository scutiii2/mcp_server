<script setup lang="ts">
import { computed } from "vue";
import type { CommandInfo } from "../api/CommandsClient";
import { capabilityLine, pickGreeting, welcomeTip } from "../utils/welcome";

// Shown in a chat with no messages. The greeting is picked once when the card
// appears, so it doesn't change while the chat stays empty.
const props = defineProps<{ commands: CommandInfo[] }>();

const greeting = pickGreeting();
const tip = computed(() => welcomeTip(props.commands.length > 0));
const capabilities = computed(() => capabilityLine(props.commands));
</script>

<template>
  <div class="welcome">
    <h2>{{ greeting }}</h2>
    <p class="tip">{{ tip }}</p>
    <p v-if="capabilities" class="caps">{{ capabilities }}</p>
  </div>
</template>

<style scoped>
.welcome {
  margin-top: 22vh;
  text-align: center;
  color: var(--muted);
}
h2 {
  margin: 0 0 10px;
  font-size: 1.4em;
  font-weight: 600;
  color: var(--text);
}
p {
  margin: 4px 0;
}
.tip {
  font-size: 0.95em;
}
.caps {
  max-width: 560px;
  margin: 10px auto 0;
  font-size: 0.85em;
}
</style>
