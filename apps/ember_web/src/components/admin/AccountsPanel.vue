<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  adminClient,
  type AccountChanges,
  type AccountStatus,
  type AdminAccount,
  type Role,
  type RoleRef,
} from "../../api/AdminClient";
import { useAuthStore } from "../../stores/auth";
import { errorMessage } from "../../utils/errors";
import SegmentedControl from "../SegmentedControl.vue";
import AccountDrawer from "./AccountDrawer.vue";
import ConfirmModal from "./ConfirmModal.vue";
import "./admin.css";

/** The overview counts (AdminView) change whenever an account does. */
const emit = defineEmits<{ changed: [] }>();

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "unverified", label: "Unverified" },
  { value: "disabled", label: "Disabled" },
] as const;
const SEARCH_DELAY_MS = 250;

/** What the confirmation dialog is asking about. */
type Pending =
  | { kind: "disable"; account: AdminAccount }
  | { kind: "delete"; account: AdminAccount }
  | { kind: "removeRole"; account: AdminAccount; role: RoleRef };

const auth = useAuthStore();

const accounts = ref<AdminAccount[]>([]);
const roles = ref<Role[]>([]);
const search = ref("");
const status = ref<AccountStatus>("all");
const loadError = ref("");
const actionError = ref("");
const notice = ref("");
const busy = ref(false);
const selectedId = ref<number | null>(null);
const pending = ref<Pending | null>(null);

const myId = computed(() => auth.account?.id ?? null);
const selected = computed(() => accounts.value.find((a) => a.id === selectedId.value) ?? null);

// Only the newest list request may fill the table: a slow answer to an earlier
// keystroke would otherwise overwrite it.
let loadSeq = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;

async function loadAccounts(): Promise<void> {
  const seq = ++loadSeq;
  try {
    const rows = await adminClient.listAccounts({ q: search.value, status: status.value });
    if (seq !== loadSeq) return;
    accounts.value = rows;
    loadError.value = "";
  } catch (err) {
    if (seq === loadSeq) loadError.value = errorMessage(err);
  }
}

async function loadRoles(): Promise<void> {
  try {
    roles.value = await adminClient.listRoles();
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

watch(search, () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadAccounts, SEARCH_DELAY_MS);
});
watch(status, loadAccounts);

onMounted(() => {
  void loadAccounts();
  void loadRoles();
});
onBeforeUnmount(() => clearTimeout(searchTimer));

function replace(updated: AdminAccount): void {
  accounts.value = accounts.value.map((a) => (a.id === updated.id ? updated : a));
}

function select(account: AdminAccount): void {
  selectedId.value = account.id;
  actionError.value = "";
  notice.value = "";
}

/** Runs one admin call for `account`, showing its error or notice. Refreshes
 * the logged-in account afterwards when it was the one changed, so the nav
 * tabs and username in the top bar follow. */
async function act(account: AdminAccount, call: () => Promise<void>, done?: string): Promise<void> {
  actionError.value = "";
  notice.value = "";
  busy.value = true;
  try {
    await call();
    if (done) notice.value = done;
    if (account.id === myId.value) await auth.refresh();
    emit("changed");
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}

function saveDetails(account: AdminAccount, changes: AccountChanges): Promise<void> {
  return act(account, async () => replace(await adminClient.updateAccount(account.id, changes)));
}

function setActive(account: AdminAccount, active: boolean): Promise<void> | undefined {
  if (!active) {
    pending.value = { kind: "disable", account };
    return;
  }
  return act(account, async () => replace(await adminClient.updateAccount(account.id, { is_active: true })));
}

function addRole(account: AdminAccount, roleId: number): Promise<void> {
  return act(account, async () => replace(await adminClient.assignRole(account.id, roleId)));
}

function sendVerification(account: AdminAccount): Promise<void> {
  return act(
    account,
    async () => {
      await adminClient.sendVerification(account.id);
    },
    `Verification email sent to ${account.email}.`,
  );
}

const confirmText = computed(() => {
  const p = pending.value;
  if (!p) return { title: "", message: "", label: "", requireText: "" };
  const name = p.account.username;
  switch (p.kind) {
    case "disable":
      return {
        title: "Disable account",
        message: `Disable '${name}'? They are logged out and can't log in until enabled.`,
        label: "Disable",
        requireText: "",
      };
    case "delete":
      return {
        title: "Delete account",
        message: `Delete '${name}' permanently? This can't be undone.`,
        label: "Delete",
        requireText: name,
      };
    case "removeRole":
      return {
        title: "Remove role",
        message: `Remove role '${p.role.name}' from '${name}'?`,
        label: "Remove",
        requireText: "",
      };
  }
});

async function confirm(): Promise<void> {
  const p = pending.value;
  if (!p) return;
  const { account } = p;
  await act(account, async () => {
    if (p.kind === "disable") {
      replace(await adminClient.updateAccount(account.id, { is_active: false }));
    } else if (p.kind === "removeRole") {
      replace(await adminClient.removeRole(account.id, p.role.id));
    } else {
      await adminClient.deleteAccount(account.id);
      accounts.value = accounts.value.filter((a) => a.id !== account.id);
      selectedId.value = null;
    }
  });
  // On failure the dialog closes too; the error shows in the drawer.
  pending.value = null;
}
</script>

<template>
  <div class="admin-panel">
    <div class="toolbar">
      <input v-model="search" type="text" placeholder="Search name or email" aria-label="Search accounts" />
      <SegmentedControl v-model="status" :options="STATUS_OPTIONS" aria-label="Account status" />
    </div>

    <p v-if="loadError" class="error">error: {{ loadError }}</p>
    <template v-if="!selected">
      <p v-if="actionError" class="error">{{ actionError }}</p>
      <p v-if="notice" class="notice">{{ notice }}</p>
    </template>

    <div :class="['layout', { open: selected }]">
      <table v-if="accounts.length" class="accounts">
        <thead>
          <tr>
            <th>Account</th>
            <th>Roles</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in accounts" :key="a.id" :class="{ selected: a.id === selectedId }" @click="select(a)">
            <td>
              <button type="button" class="name" :aria-pressed="a.id === selectedId" @click.stop="select(a)">
                {{ a.username }}
              </button>
              <span v-if="a.id === myId" class="badge">you</span>
              <span v-if="a.is_protected" class="badge">protected</span>
              <div class="muted email">{{ a.email }}</div>
            </td>
            <td>
              <span v-for="r in a.roles" :key="r.id" class="chip fixed">{{ r.name }}</span>
              <span v-if="a.roles.length === 0" class="muted">No roles</span>
            </td>
            <td>
              <span v-if="!a.is_active" class="badge warn">disabled</span>
              <span v-else-if="!a.email_verified" class="badge warn">unverified</span>
              <span v-else class="badge">active</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!loadError" class="muted empty">No accounts match.</p>

      <AccountDrawer
        v-if="selected"
        :account="selected"
        :roles="roles"
        :is-self="selected.id === myId"
        :busy="busy"
        :error="actionError"
        :notice="notice"
        @close="selectedId = null"
        @save="(changes) => saveDetails(selected!, changes)"
        @set-active="(active) => setActive(selected!, active)"
        @add-role="(roleId) => addRole(selected!, roleId)"
        @remove-role="(role) => (pending = { kind: 'removeRole', account: selected!, role })"
        @send-verification="sendVerification(selected!)"
        @remove="pending = { kind: 'delete', account: selected! }"
      />
    </div>

    <ConfirmModal
      :open="pending !== null"
      :title="confirmText.title"
      :message="confirmText.message"
      :confirm-label="confirmText.label"
      :require-text="confirmText.requireText"
      danger
      :busy="busy"
      @confirm="confirm"
      @close="pending = null"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.toolbar input {
  flex: 1 1 200px;
  min-width: 0;
}
.layout {
  display: grid;
  gap: 12px;
  align-items: start;
}
.layout.open {
  grid-template-columns: minmax(0, 1fr) 250px;
}
@media (max-width: 720px) {
  .layout.open {
    grid-template-columns: minmax(0, 1fr);
  }
}
.accounts {
  width: 100%;
  border-collapse: collapse;
}
.accounts th {
  padding: 6px 8px;
  text-align: left;
  font-size: 0.8em;
  font-weight: 500;
  color: var(--muted);
}
.accounts td {
  padding: 8px;
  border-top: 1px solid var(--border);
  vertical-align: top;
}
.accounts tbody tr {
  cursor: pointer;
}
.accounts tbody tr:hover,
.accounts tbody tr.selected {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.name {
  margin-right: 6px;
  padding: 0;
  border: none;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--text);
  background: none;
  overflow-wrap: anywhere;
}
.email {
  font-size: 0.85em;
  overflow-wrap: anywhere;
}
.chip {
  margin: 0 4px 4px 0;
}
.empty {
  margin: 12px 0;
}
</style>
