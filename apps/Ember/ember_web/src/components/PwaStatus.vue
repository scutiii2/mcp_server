<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useRegisterSW } from "virtual:pwa-register/vue";

defineProps<{ appName: string; offlineMessage: string }>();
interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}
const online = ref(navigator.onLine);
const reconnectNeeded = ref(!navigator.onLine);
const installPrompt = ref<InstallPrompt | null>(null);
const installing = ref(false);
const updating = ref(false);
const error = ref("");
let updateAccepted = false;
let externalUpdate = false;
const { needRefresh, updateServiceWorker } = useRegisterSW({
  onNeedReload() {
    if (updateAccepted) window.location.reload();
    else {
      // Updating another tab must not discard this tab's chat or unsaved form.
      externalUpdate = true;
      needRefresh.value = true;
    }
  },
});
function retry(): void { window.location.reload(); }
function connectionChanged(): void {
  online.value = navigator.onLine;
  if (!online.value) reconnectNeeded.value = true;
}
function offerInstall(event: Event): void {
  event.preventDefault();
  installPrompt.value = event as InstallPrompt;
}
function installed(): void { installPrompt.value = null; }
async function install(): Promise<void> {
  const prompt = installPrompt.value;
  if (!prompt || installing.value) return;
  installing.value = true;
  error.value = "";
  try {
    await prompt.prompt();
    await prompt.userChoice;
    installPrompt.value = null;
  } catch { error.value = "Could not open the install prompt. Try your browser's install menu."; }
  finally { installing.value = false; }
}
async function update(): Promise<void> {
  if (updating.value) return;
  updating.value = true;
  error.value = "";
  updateAccepted = true;
  try {
    if (externalUpdate) window.location.reload();
    else await updateServiceWorker();
  }
  catch { updateAccepted = false; error.value = "Could not update. Reconnect and try again."; }
  finally { updating.value = false; }
}
onMounted(() => {
  window.addEventListener("online", connectionChanged);
  window.addEventListener("offline", connectionChanged);
  window.addEventListener("beforeinstallprompt", offerInstall);
  window.addEventListener("appinstalled", installed);
});
onUnmounted(() => {
  window.removeEventListener("online", connectionChanged);
  window.removeEventListener("offline", connectionChanged);
  window.removeEventListener("beforeinstallprompt", offerInstall);
  window.removeEventListener("appinstalled", installed);
});
</script>

<template>
  <aside v-if="!online || reconnectNeeded || needRefresh || installPrompt || error" class="pwa-status" aria-label="App status">
    <p v-if="!online" role="status"><strong>You’re offline.</strong> {{ offlineMessage }} <button type="button" @click="retry">Retry</button></p>
    <p v-if="online && reconnectNeeded" role="status">Back online. Reload to reconnect. <button type="button" @click="retry">Retry</button></p>
    <p v-if="needRefresh && online" role="status">
      A new version of {{ appName }} is ready. Save your work before reloading.
      <button type="button" :disabled="updating" :aria-busy="updating" @click="update">{{ updating ? 'Updating…' : 'Reload to update' }}</button>
      <button type="button" @click="needRefresh = false">Later</button>
    </p>
    <p v-if="installPrompt && online">Install {{ appName }} for quick access.
      <button type="button" :disabled="installing" :aria-busy="installing" @click="install">{{ installing ? 'Installing…' : 'Install app' }}</button>
      <button type="button" @click="installPrompt = null">Dismiss</button>
    </p>
    <p v-if="error" role="alert">{{ error }}</p>
  </aside>
</template>

<style scoped>
.pwa-status { flex-shrink: 0; padding: 8px 16px; border-bottom: 1px solid var(--border); background: var(--surface); }
p { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; font-size: .9em; }
p + p { margin-top: 8px; }
button { min-height: 36px; padding: 4px 12px; border: 1px solid var(--border); border-radius: var(--radius-full); background: var(--bg); color: var(--text); font: inherit; cursor: pointer; }
button:disabled { cursor: wait; opacity: .6; }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (pointer: coarse) { button { min-height: 44px; } }
</style>
