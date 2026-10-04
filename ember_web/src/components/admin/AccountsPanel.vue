<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { adminClient, type AccountChanges, type AdminAccount, type Role } from "../../api/AdminClient";
import { useAuthStore } from "../../stores/auth";
import { errorMessage, formatUtc } from "../../utils/errors";
import "./admin.css";

const auth = useAuthStore();

const accounts = ref<AdminAccount[]>([]);
const roles = ref<Role[]>([]);
const loadError = ref("");
const actionError = ref("");
const notice = ref("");
// Id of the account whose request is in flight; its buttons are disabled.
const busyId = ref<number | null>(null);

// One inline edit form at a time.
const editing = reactive({ id: null as number | null, username: "", email: "" });
// Per-account choice in the "add role" dropdown.
const roleChoice = reactive<Record<number, number | "">>({});

const myId = computed(() => auth.account?.id ?? null);

async function load(): Promise<void> {
  loadError.value = "";
  try {
    [accounts.value, roles.value] = await Promise.all([adminClient.listAccounts(), adminClient.listRoles()]);
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

function missingRoles(account: AdminAccount): Role[] {
  const held = new Set(account.roles.map((r) => r.id));
  return roles.value.filter((r) => !held.has(r.id));
}

function replace(updated: AdminAccount): void {
  accounts.value = accounts.value.map((a) => (a.id === updated.id ? updated : a));
}

/** Runs one admin call for `account`, showing its error or notice. Refreshes
 * the logged-in account afterwards when it was the one changed, so the nav
 * tabs and username in the top bar follow. */
async function act(account: AdminAccount, call: () => Promise<void>, done?: string): Promise<void> {
  actionError.value = "";
  notice.value = "";
  busyId.value = account.id;
  try {
    await call();
    if (done) notice.value = done;
    if (account.id === myId.value) await auth.refresh();
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    busyId.value = null;
  }
}

function startEdit(account: AdminAccount): void {
  editing.id = account.id;
  editing.username = account.username;
  editing.email = account.email;
}

function saveEdit(account: AdminAccount): Promise<void> {
  const changes: AccountChanges = {};
  if (editing.username.trim() !== account.username) changes.username = editing.username.trim();
  if (editing.email.trim() !== account.email) changes.email = editing.email.trim();
  return act(account, async () => {
    if (Object.keys(changes).length) replace(await adminClient.updateAccount(account.id, changes));
    editing.id = null;
  });
}

function setActive(account: AdminAccount, active: boolean): Promise<void> | undefined {
  if (!active && !confirm(`Disable '${account.username}'? They are logged out and can't log in until enabled.`)) {
    return;
  }
  return act(account, async () => replace(await adminClient.updateAccount(account.id, { is_active: active })));
}

function addRole(account: AdminAccount): Promise<void> | undefined {
  const roleId = roleChoice[account.id];
  if (roleId === undefined || roleId === "") return;
  return act(account, async () => {
    replace(await adminClient.assignRole(account.id, roleId));
    roleChoice[account.id] = "";
  });
}

function removeRole(account: AdminAccount, roleId: number, roleName: string): Promise<void> | undefined {
  if (!confirm(`Remove role '${roleName}' from '${account.username}'?`)) return;
  return act(account, async () => replace(await adminClient.removeRole(account.id, roleId)));
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

function remove(account: AdminAccount): Promise<void> | undefined {
  if (!confirm(`Delete '${account.username}' permanently? This can't be undone.`)) return;
  return act(account, async () => {
    await adminClient.deleteAccount(account.id);
    accounts.value = accounts.value.filter((a) => a.id !== account.id);
  });
}

onMounted(load);
</script>

<template>
  <div class="admin-panel">
    <p v-if="loadError" class="error">error: {{ loadError }}</p>
    <p v-if="actionError" class="error">{{ actionError }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <div v-for="a in accounts" :key="a.id" class="card">
      <form v-if="editing.id === a.id" class="row-form" @submit.prevent="saveEdit(a)">
        <input v-model="editing.username" type="text" aria-label="Username" required />
        <input v-model="editing.email" type="email" aria-label="Email" required />
        <button class="primary" :disabled="busyId === a.id">Save</button>
        <button type="button" class="small" @click="editing.id = null">Cancel</button>
      </form>
      <div v-else class="card-head">
        <span class="card-title">{{ a.username }}</span>
        <span class="muted">{{ a.email }}</span>
        <span v-if="a.id === myId" class="badge">you</span>
        <span v-if="a.is_protected" class="badge">protected</span>
        <span v-if="!a.email_verified" class="badge warn">unverified</span>
        <span v-if="!a.is_active" class="badge warn">disabled</span>
      </div>

      <div class="chips">
        <span v-for="r in a.roles" :key="r.id" class="chip" :class="{ fixed: a.is_protected }">
          {{ r.name }}
          <button
            v-if="!a.is_protected"
            type="button"
            class="chip-x"
            :aria-label="`Remove role ${r.name}`"
            :disabled="busyId === a.id"
            @click="removeRole(a, r.id, r.name)"
          >
            ×
          </button>
        </span>
        <span v-if="a.roles.length === 0" class="muted">No roles</span>
        <template v-if="missingRoles(a).length">
          <select v-model="roleChoice[a.id]" aria-label="Role to add" @change="addRole(a)">
            <option value="">+ Add role</option>
            <option v-for="r in missingRoles(a)" :key="r.id" :value="r.id">{{ r.name }}</option>
          </select>
        </template>
      </div>

      <div class="actions">
        <span class="muted">Joined {{ formatUtc(a.created_at) }}</span>
        <template v-if="!a.is_protected">
          <button type="button" class="small" :disabled="busyId === a.id" @click="startEdit(a)">Edit</button>
          <button
            v-if="!a.email_verified"
            type="button"
            class="small"
            :disabled="busyId === a.id"
            @click="sendVerification(a)"
          >
            Send verification
          </button>
          <template v-if="a.id !== myId">
            <button
              type="button"
              class="small"
              :disabled="busyId === a.id"
              @click="setActive(a, !a.is_active)"
            >
              {{ a.is_active ? "Disable" : "Enable" }}
            </button>
            <button type="button" class="small danger" :disabled="busyId === a.id" @click="remove(a)">
              Delete
            </button>
          </template>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.actions .muted {
  margin-right: auto;
  font-size: 0.85em;
  align-self: center;
}
</style>
