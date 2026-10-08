<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { sharesClient, type ShareCreated, type ShareExpiry, type ShareInfo } from "../api/SharesClient";
import { errorMessage, formatUtc } from "../utils/errors";
import ConfirmModal from "./ConfirmModal.vue";
import CopyButton from "./CopyButton.vue";

/** Makes, lists and revokes read-only share links for one chat. A link's
 * secret exists only in the response that creates it, so it lives here in
 * memory, is shown once, and is dropped when the dialog closes; the list
 * below shows the links that exist without their secrets. */

const props = defineProps<{ open: boolean; chatId: string | null }>();
const emit = defineEmits<{ close: [] }>();

const EXPIRIES: { value: ShareExpiry; label: string }[] = [
  { value: 1, label: "1 day" },
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: null, label: "Never" },
];

const dialog = ref<HTMLDialogElement | null>(null);
const expiry = ref<ShareExpiry>(7);
const links = ref<ShareInfo[]>([]);
const loading = ref(false);
const creating = ref(false);
const error = ref("");
// The link just made, with its secret: shown once.
const fresh = ref<{ id: number; url: string } | null>(null);

const shareUrl = (token: string): string => `${window.location.origin}/shared/${token}`;

// Bumped on every open and chat change: answers for an older one are ignored.
let generation = 0;

async function loadLinks(): Promise<void> {
  const started = generation;
  const chatId = props.chatId;
  if (!chatId) return;
  loading.value = true;
  try {
    const list = await sharesClient.list(chatId);
    if (started === generation) links.value = list;
  } catch (err) {
    if (started === generation) error.value = errorMessage(err);
  } finally {
    if (started === generation) loading.value = false;
  }
}

function reset(): void {
  generation += 1;
  links.value = [];
  fresh.value = null;
  error.value = "";
  expiry.value = 7;
  creating.value = false;
}

watch(
  () => [props.open, props.chatId] as const,
  async ([isOpen]) => {
    reset();
    await nextTick();
    if (isOpen && !dialog.value?.open) dialog.value?.showModal();
    else if (!isOpen && dialog.value?.open) dialog.value.close();
    if (isOpen) void loadLinks();
  },
);

async function create(): Promise<void> {
  const chatId = props.chatId;
  if (!chatId || creating.value) return;
  const started = generation;
  creating.value = true;
  error.value = "";
  try {
    const made: ShareCreated = await sharesClient.create(chatId, expiry.value);
    if (started !== generation) return;
    const { token, ...info } = made;
    fresh.value = { id: info.id, url: shareUrl(token) };
    links.value = [info, ...links.value];
  } catch (err) {
    if (started === generation) error.value = errorMessage(err);
  } finally {
    if (started === generation) creating.value = false;
  }
}

// Turning a link off asks first, in the confirmation dialog.
const pendingRevoke = ref<ShareInfo | null>(null);

async function revoke(link: ShareInfo): Promise<void> {
  pendingRevoke.value = null;
  const started = generation;
  error.value = "";
  try {
    await sharesClient.revoke(link.id);
  } catch (err) {
    if (started === generation) error.value = errorMessage(err);
    return;
  }
  if (started !== generation) return;
  links.value = links.value.filter((l) => l.id !== link.id);
  if (fresh.value?.id === link.id) fresh.value = null;
}

const expiryText = (link: ShareInfo): string =>
  link.expires_at ? `expires ${formatUtc(link.expires_at)}` : "never expires";

const hasLinks = computed(() => links.value.length > 0);
</script>

<template>
  <dialog ref="dialog" class="share" aria-label="Share this chat" @close="emit('close')" @cancel.prevent="emit('close')">
    <header>
      <h3>Share this chat</h3>
      <button type="button" class="close" aria-label="Close" @click="emit('close')">×</button>
    </header>

    <p class="intro">
      Anyone with the link can read a <strong>read-only copy</strong> of this chat as it is now, without logging in.
      Your questions and the answers are included; tool output, summaries and the text of attached files are not.
      Later messages are never added.
    </p>

    <form class="create" @submit.prevent="create">
      <label>
        Link works for
        <select v-model="expiry">
          <option v-for="e in EXPIRIES" :key="String(e.value)" :value="e.value">{{ e.label }}</option>
        </select>
      </label>
      <button type="submit" class="primary" :disabled="creating || !chatId">
        {{ creating ? "Creating …" : "Create link" }}
      </button>
    </form>

    <div v-if="fresh" class="fresh" role="status">
      <p>
        <strong>Copy this link now.</strong> It is shown only once; if you lose it, turn it off below and make a new
        one.
      </p>
      <div class="url">
        <input type="text" readonly :value="fresh.url" aria-label="Share link" @focus="($event.target as HTMLInputElement).select()" />
        <CopyButton :text="fresh.url" label="Copy link" />
      </div>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <h4>Links to this chat</h4>
    <p v-if="loading && !hasLinks" class="muted">Loading …</p>
    <p v-else-if="!hasLinks" class="muted">None yet.</p>
    <ul v-else class="links">
      <li v-for="l in links" :key="l.id">
        <div class="info">
          <span>Created {{ formatUtc(l.created_at) }}<template v-if="l.id === fresh?.id"> (new)</template></span>
          <span class="muted">{{ expiryText(l) }} · {{ l.message_count }} messages</span>
        </div>
        <button type="button" class="link danger" @click="pendingRevoke = l">Turn off</button>
      </li>
    </ul>
    <p class="muted small">Deleting the chat also turns its links off.</p>
    <ConfirmModal
      v-if="pendingRevoke"
      open
      title="Turn off link"
      message="Turn this link off? Anyone who has it will no longer be able to open the chat."
      confirm-label="Turn off"
      danger
      @confirm="revoke(pendingRevoke)"
      @close="pendingRevoke = null"
    />
  </dialog>
</template>

<style scoped>
.share {
  width: min(560px, calc(100vw - 32px));
  max-height: calc(100vh - 64px);
  padding: 18px 20px 20px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  color: var(--text);
  background: var(--surface);
}
.share::backdrop {
  background: rgb(0 0 0 / 45%);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h3,
h4 {
  margin: 0;
  font-size: 1em;
}
h4 {
  margin-top: 16px;
  font-size: 0.9em;
  color: var(--muted);
}
.close {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1.4em;
  line-height: 1;
  color: var(--muted);
}
.intro {
  margin: 8px 0 12px;
  font-size: 0.9em;
  color: var(--muted);
}
.create {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}
.create label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.85em;
  color: var(--muted);
}
.create select {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.primary {
  padding: 6px 16px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-full);
  cursor: pointer;
  color: var(--accent-contrast);
  background: var(--accent);
}
.primary:disabled {
  cursor: default;
  opacity: 0.4;
}
.fresh {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
}
.fresh p {
  margin: 0 0 8px;
  font-size: 0.85em;
}
.url {
  display: flex;
  align-items: center;
  gap: 6px;
}
.url input {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: calc(var(--radius-lg) - 10px);
  color: var(--text);
  background: var(--bg);
  font-family: var(--mono);
  font-size: 0.8em;
}
.error {
  margin: 10px 0 0;
  font-size: 0.9em;
  color: var(--danger);
}
.muted {
  color: var(--muted);
}
.small {
  font-size: 0.8em;
}
.links {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}
.links li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  font-size: 0.85em;
}
.link {
  padding: 2px 8px;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.link.danger:hover {
  color: var(--danger);
  background: var(--bg);
}
</style>
