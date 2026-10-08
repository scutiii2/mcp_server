<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import type { UserExtension } from "../api/UserExtensionsClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import AddExtensionModal from "../components/AddExtensionModal.vue";
import SupermarketItem from "../components/SupermarketItem.vue";
import UserExtensionModal from "../components/UserExtensionModal.vue";
import { useEveryoneSwitch } from "../composables/useEveryoneSwitch";
import { useAccountCapabilitiesStore } from "../stores/accountCapabilities";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { useUserExtensionsStore } from "../stores/userExtensions";
import { errorMessage } from "../utils/errors";
import { userExtensionSummary } from "../utils/userExtensions";

/** Everything the account can add: mcp_server's built-in capabilities and its
 * extensions, in two sections, with Add and Disable per row. A user can only
 * add or disable; extensions.manage also permits adding and removing extensions
 * on the server, and admin.manage permits turning a built-in capability back on
 * for everyone. Two exclusive filter
 * chips (Enabled, Disabled) narrow both lists; the choice lives in the address
 * (?state=enabled|disabled). */

const auth = useAuthStore();
const account = useAccountCapabilitiesStore();
const chat = useChatStore();
const userExt = useUserExtensionsStore();
const route = useRoute();
const router = useRouter();

const capabilities = ref<CapabilityInfo[]>([]);
const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
const addOpen = ref(false);
const pendingRemove = ref<ExtensionInfo | null>(null);
const removing = ref(false);
const canUsePrivate = computed(() => auth.hasPermission("chat.use"));
const modalOpen = ref(false);
const editing = ref<UserExtension | null>(null);
const pendingRemovePrivate = ref<UserExtension | null>(null);
const removingPrivate = ref(false);

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
const canManageExtensions = computed(() => auth.hasPermission("extensions.manage"));
// Capabilities need tools.use; the extension list needs chat.use or tools.use.
const canTools = computed(() => auth.hasPermission("tools.use"));
const accountLoading = computed(() => !account.ready && account.error === "");

type StateFilter = "enabled" | "disabled" | null;
const stateFilter = computed<StateFilter>(() =>
  route.query.state === "enabled" ? "enabled" : route.query.state === "disabled" ? "disabled" : null,
);

function chooseFilter(next: "enabled" | "disabled"): void {
  const query = { ...route.query };
  if (stateFilter.value === next) delete query.state;
  else query.state = next;
  void router.replace({ query });
}

const shown = (added: boolean): boolean => stateFilter.value === null || (stateFilter.value === "enabled") === added;
const byLabel = <T extends { label?: string | null; name?: string; id?: string }>(a: T, b: T): number =>
  (a.label ?? a.name ?? a.id ?? "").localeCompare(b.label ?? b.name ?? b.id ?? "");

const addedCapabilities = computed(() => new Set(account.capabilities));
const addedExtensions = computed(() => new Set(account.extensions));
const builtIn = computed(() =>
  [...capabilities.value].sort(byLabel).filter((c) => shown(addedCapabilities.value.has(c.name))),
);
const extensionRows = computed(() =>
  [...extensions.value].sort(byLabel).filter((e) => shown(addedExtensions.value.has(e.id))),
);

const privateRows = computed(() => [...userExt.items].sort(byLabel).filter((i) => shown(i.enabled)));

function openAdd(): void {
  editing.value = null;
  modalOpen.value = true;
}

function openEdit(item: UserExtension): void {
  editing.value = item;
  modalOpen.value = true;
}

async function confirmRemovePrivate(): Promise<void> {
  const item = pendingRemovePrivate.value;
  if (!item) return;
  actionError.value = "";
  removingPrivate.value = true;
  try {
    await userExt.remove(item.id);
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    removingPrivate.value = false;
    pendingRemovePrivate.value = null;
  }
}

const toolsText = (n: number): string => `${n} tool${n === 1 ? "" : "s"}`;
const capabilitySummary = (c: CapabilityInfo): string => (c.enabled ? toolsText(c.tools.length) : "Off for everyone");
const extensionSummary = (e: ExtensionInfo): string => (e.status === "connected" ? toolsText(e.tools.length) : "Not connected");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [caps, exts] = await Promise.all([
      canTools.value ? commandsClient.capabilities() : [],
      extensionsClient.list(),
    ]);
    capabilities.value = caps;
    extensions.value = exts;
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

const {
  pending: pendingSwitch,
  error: switchError,
  copy: switchCopy,
  ask: askSwitch,
  cancel: cancelSwitch,
  confirm: confirmSwitch,
} = useEveryoneSwitch((updated) => {
  capabilities.value = capabilities.value.map((c) => (c.name === updated.name ? updated : c));
});

function onAdded(created: ExtensionInfo): void {
  extensions.value = [...extensions.value.filter((e) => e.id !== created.id), created];
  addOpen.value = false;
  chat.refreshCommands();
}

const removeMessage = computed(() =>
  pendingRemove.value
    ? `Remove "${pendingRemove.value.label}"? Its tools stop being offered to every mcp_server client.`
    : "",
);

async function confirmRemove(): Promise<void> {
  const extension = pendingRemove.value;
  if (!extension) return;
  actionError.value = "";
  removing.value = true;
  try {
    await extensionsClient.remove(extension.id);
    extensions.value = extensions.value.filter((e) => e.id !== extension.id);
    // ember_api cleared the extension from every account; read our copy again.
    await account.refresh();
    chat.refreshCommands();
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    removing.value = false;
    pendingRemove.value = null;
  }
}

onMounted(() => {
  void load();
  // Each one's status comes from a live probe, so look again whenever the page opens.
  if (canUsePrivate.value) void userExt.refresh();
});
</script>

<template>
  <section class="shop-view">
    <div class="column">
      <RouterLink to="/capabilities" class="back">&larr; Back to capabilities</RouterLink>
      <div class="head">
        <h2>Supermarket</h2>
        <div class="chips" role="group" aria-label="Filter by state">
          <button
            type="button"
            :class="['chip', { on: stateFilter === 'enabled' }]"
            :aria-pressed="stateFilter === 'enabled'"
            @click="chooseFilter('enabled')"
          >
            Enabled
          </button>
          <button
            type="button"
            :class="['chip', { on: stateFilter === 'disabled' }]"
            :aria-pressed="stateFilter === 'disabled'"
            @click="chooseFilter('disabled')"
          >
            Disabled
          </button>
        </div>
      </div>
      <p class="muted intro">Add the capabilities and extensions you want. They appear on your Capabilities page and become available to the agent in your chats.</p>

      <p v-if="loading || accountLoading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="!account.ready" class="error">error: {{ account.error }}</p>
      <p v-if="actionError || switchError || (account.ready && account.error) || userExt.error" class="error" role="alert">
        {{ actionError || switchError || account.error || userExt.error }}
      </p>

      <template v-if="!loading && !loadError && account.ready">
        <template v-if="canTools">
          <h4 class="group-title">Built-in</h4>
          <SupermarketItem
            v-for="c in builtIn"
            :key="c.name"
            :label="c.label ?? c.name"
            :name="c.name"
            icon="builtin"
            :summary="capabilitySummary(c)"
            :added="addedCapabilities.has(c.name)"
            :locked="!c.enabled"
            @add="account.setCapability(c.name, true)"
            @disable="account.setCapability(c.name, false)"
          >
            <template v-if="isAdmin && !c.enabled" #actions>
              <button type="button" class="everyone" @click="askSwitch(c)">Turn on for everyone</button>
            </template>
          </SupermarketItem>
          <p v-if="builtIn.length === 0" class="muted">No built-in capabilities match this filter.</p>
        </template>

        <div class="section-head">
          <h4 class="group-title">Extensions</h4>
          <button v-if="canManageExtensions" type="button" class="primary" @click="addOpen = true">Add extension</button>
        </div>
        <SupermarketItem
          v-for="e in extensionRows"
          :key="e.id"
          :label="e.label"
          :name="e.id"
          icon="extension"
          :summary="extensionSummary(e)"
          :failed="e.status !== 'connected'"
          :added="addedExtensions.has(e.id)"
          @add="account.setExtension(e.id, true)"
          @disable="account.setExtension(e.id, false)"
        >
          <template v-if="canManageExtensions" #actions>
            <button type="button" class="remove" :aria-label="`Remove ${e.label}`" @click="pendingRemove = e">Remove</button>
          </template>
        </SupermarketItem>
        <p v-if="extensionRows.length === 0" class="muted">No extensions match this filter.</p>

        <template v-if="canUsePrivate">
          <div class="section-head">
            <h4 class="group-title">My extensions</h4>
            <button type="button" class="primary" @click="openAdd">Add your own extension</button>
          </div>
          <p class="muted hint">MCP servers only you can see. Their tools always ask before they run.</p>
          <SupermarketItem
            v-for="i in privateRows"
            :key="i.id"
            :label="i.label"
            :name="i.id"
            icon="extension"
            :summary="userExtensionSummary(i)"
            :detail="i.enabled && i.status !== 'connected' ? (i.error ?? '') : ''"
            :failed="i.enabled && i.status === 'error'"
            :added="i.enabled"
            add-label="Enable"
            added-label="Enabled"
            @add="userExt.setEnabled(i.id, true)"
            @disable="userExt.setEnabled(i.id, false)"
          >
            <template #actions>
              <button type="button" class="edit" :aria-label="`Edit ${i.label}`" @click="openEdit(i)">Edit</button>
              <button type="button" class="remove" :aria-label="`Remove ${i.label}`" @click="pendingRemovePrivate = i">
                Remove
              </button>
            </template>
          </SupermarketItem>
          <p v-if="privateRows.length === 0" class="muted">
            {{
              userExt.items.length
                ? "No private extensions match this filter."
                : "You haven't added any private extensions."
            }}
          </p>
        </template>
      </template>
    </div>

    <ConfirmModal
      v-if="pendingSwitch"
      open
      :title="switchCopy.title"
      :message="switchCopy.message"
      :confirm-label="switchCopy.label"
      :danger="pendingSwitch.enabled"
      @confirm="confirmSwitch"
      @close="cancelSwitch"
    />

    <ConfirmModal
      v-if="canManageExtensions && pendingRemove"
      open
      title="Remove extension"
      :message="removeMessage"
      confirm-label="Remove"
      danger
      :busy="removing"
      @confirm="confirmRemove"
      @close="pendingRemove = null"
    />

    <AddExtensionModal v-if="canManageExtensions" :open="addOpen" @close="addOpen = false" @added="onAdded" />

    <UserExtensionModal
      v-if="canUsePrivate"
      :open="modalOpen"
      :extension="editing"
      @close="modalOpen = false"
      @saved="modalOpen = false"
    />

    <ConfirmModal
      v-if="pendingRemovePrivate"
      open
      title="Remove private extension"
      :message="`Remove &quot;${pendingRemovePrivate.label}&quot;? Its saved headers are deleted too.`"
      confirm-label="Remove"
      danger
      :busy="removingPrivate"
      @confirm="confirmRemovePrivate"
      @close="pendingRemovePrivate = null"
    />
  </section>
</template>

<style scoped>
.shop-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
.back {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 0.85em;
  color: var(--accent);
  text-decoration: none;
}
.back:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
h2 {
  margin: 0;
  font-size: 1.2em;
}
.chips {
  display: flex;
  gap: 8px;
}
.chip {
  padding: 4px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.chip:hover {
  border-color: var(--accent);
}
.chip.on {
  border-color: var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.chip:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.intro {
  margin: 0 0 12px;
  font-size: 0.9em;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.group-title {
  margin: 16px 2px 8px;
  font-size: 0.8em;
  font-weight: 500;
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.everyone,
.edit,
.remove {
  padding: 4px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.edit:hover,
.everyone:hover {
  color: var(--text);
  border-color: var(--accent);
}
.remove {
  border-color: var(--danger);
  color: var(--danger);
}
.everyone:focus-visible,
.edit:focus-visible,
.remove:focus-visible,
.primary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.muted {
  color: var(--muted);
}
.hint {
  margin: 0 2px 8px;
  font-size: 0.85em;
}
.error {
  color: var(--danger);
}
</style>
