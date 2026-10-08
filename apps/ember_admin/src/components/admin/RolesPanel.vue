<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { adminClient, type PermissionInfo, type Role, type RoleChanges } from "../../api/AdminClient";
import { useAuthStore } from "../../stores/auth";
import { errorMessage } from "../../utils/errors";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "./ConfirmModal.vue";
import RoleEditor from "./RoleEditor.vue";
import "./admin.css";

const auth = useAuthStore();

const roles = ref<Role[]>([]);
const permissions = ref<PermissionInfo[]>([]);
const selectedId = ref<number | null>(null);
const loadError = ref("");
const actionError = ref("");
const busy = ref(false);
// The last change to the open role went through; shown as a "Saved" chip.
const saved = ref(false);
const pendingDelete = ref<Role | null>(null);

const creating = ref(false);
const newRole = reactive({ name: "", description: "", error: "", saving: false });

const selected = computed(() => roles.value.find((r) => r.id === selectedId.value) ?? null);

async function load(): Promise<void> {
  loadError.value = "";
  try {
    [roles.value, permissions.value] = await Promise.all([adminClient.listRoles(), adminClient.listPermissions()]);
    if (!selected.value) selectedId.value = roles.value[0]?.id ?? null;
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

function replace(updated: Role): void {
  roles.value = roles.value.map((r) => (r.id === updated.id ? updated : r));
}

function select(role: Role): void {
  selectedId.value = role.id;
  actionError.value = "";
  saved.value = false;
}

/** Runs one admin call for `role`. When the logged-in account holds the
 * role, its permissions may have changed, so the account is re-read. */
async function act(role: Role, call: () => Promise<void>): Promise<void> {
  actionError.value = "";
  saved.value = false;
  busy.value = true;
  const held = auth.account?.roles.includes(role.name) ?? false;
  try {
    await call();
    if (held) await auth.refresh();
    saved.value = true;
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}

function openCreate(): void {
  newRole.name = "";
  newRole.description = "";
  newRole.error = "";
  creating.value = true;
}

async function createRole(): Promise<void> {
  newRole.error = "";
  newRole.saving = true;
  try {
    const role = await adminClient.createRole(newRole.name.trim(), newRole.description.trim() || null);
    roles.value = [...roles.value, role].sort((a, b) => a.name.localeCompare(b.name));
    selectedId.value = role.id;
    actionError.value = "";
    creating.value = false;
  } catch (err) {
    newRole.error = errorMessage(err);
  } finally {
    newRole.saving = false;
  }
}

function togglePermission(role: Role, name: string, granted: boolean): Promise<void> {
  return act(role, async () => {
    replace(granted ? await adminClient.grantPermission(role.id, name) : await adminClient.revokePermission(role.id, name));
  });
}

function saveDetails(role: Role, changes: RoleChanges): Promise<void> {
  return act(role, async () => replace(await adminClient.updateRole(role.id, changes)));
}

const deleteMessage = computed(() => {
  const role = pendingDelete.value;
  if (!role) return "";
  const users = role.account_count === 1 ? "1 account" : `${role.account_count} accounts`;
  return `Delete role '${role.name}'? It is removed from ${users}.`;
});

async function confirmDelete(): Promise<void> {
  const role = pendingDelete.value;
  if (!role) return;
  await act(role, async () => {
    await adminClient.deleteRole(role.id);
    roles.value = roles.value.filter((r) => r.id !== role.id);
    if (selectedId.value === role.id) selectedId.value = roles.value[0]?.id ?? null;
  });
  // On failure the dialog closes too; the error shows beside the role.
  pendingDelete.value = null;
}

onMounted(load);
</script>

<template>
  <div class="admin-panel">
    <header class="section-head">
      <div><h3>Roles &amp; permissions</h3><p>Define what each role can access.</p></div>
      <button v-if="auth.hasPermission('roles.manage')" type="button" class="primary new" @click="openCreate">+ New role</button>
    </header>
    <p v-if="loadError" class="error">error: {{ loadError }}</p>

    <div class="layout">
      <nav class="list" aria-label="Roles">
        <ul>
          <li v-for="r in roles" :key="r.id">
            <button type="button" :class="['role', { selected: r.id === selectedId }]" :aria-pressed="r.id === selectedId" @click="select(r)">
              <span class="role-name">{{ r.name }}</span>
              <span v-if="r.is_protected" class="badge">protected</span>
              <span class="muted count">{{ r.account_count }} {{ r.account_count === 1 ? "account" : "accounts" }}</span>
            </button>
          </li>
        </ul>
      </nav>

      <RoleEditor
        v-if="selected"
        :role="selected"
        :permissions="permissions"
        :busy="busy"
        :error="actionError"
        :saved="saved"
        @save="(changes) => saveDetails(selected!, changes)"
        @toggle-permission="(name, granted) => togglePermission(selected!, name, granted)"
        @remove="pendingDelete = selected"
      />
      <p v-else-if="!loadError" class="muted">No roles yet. Create one to get started.</p>
    </div>

    <BaseModal :open="creating" title="New role" @close="creating = false">
      <form class="create" @submit.prevent="createRole">
        <input v-model="newRole.name" type="text" aria-label="Role name" placeholder="Role name" maxlength="80" required />
        <input v-model="newRole.description" type="text" aria-label="Description" placeholder="Description (optional)" maxlength="255" />
        <p v-if="newRole.error" class="error">{{ newRole.error }}</p>
        <div class="create-actions">
          <button type="button" class="small" @click="creating = false">Cancel</button>
          <button class="primary" :disabled="newRole.saving || !newRole.name.trim()">Create role</button>
        </div>
      </form>
    </BaseModal>

    <ConfirmModal
      :open="pendingDelete !== null"
      title="Delete role"
      :message="deleteMessage"
      confirm-label="Delete"
      danger
      :require-text="pendingDelete && pendingDelete.account_count > 0 ? pendingDelete.name : ''"
      :busy="busy"
      @confirm="confirmDelete"
      @close="pendingDelete = null"
    />
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 767px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
.list ul {
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.list li + li {
  border-top: 1px solid var(--border);
}
.new {
  flex-shrink: 0;
}
.role {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 6px;
  width: 100%;
  padding: 14px 16px;
  border: none;
  cursor: pointer;
  font: inherit;
  text-align: left;
  color: var(--text);
  background: transparent;
}
.role:hover,
.role.selected {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.role-name {
  overflow-wrap: anywhere;
  font-weight: 600;
}
.count {
  flex-basis: 100%;
  font-size: 0.8em;
}
.create {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.create input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
