<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { adminClient, type PermissionInfo, type Role, type RoleChanges } from "../../api/AdminClient";
import { useAuthStore } from "../../stores/auth";
import { errorMessage } from "../../utils/errors";
import "./admin.css";

const auth = useAuthStore();

const roles = ref<Role[]>([]);
const permissions = ref<PermissionInfo[]>([]);
const loadError = ref("");
const actionError = ref("");
const busyId = ref<number | null>(null);

const newRole = reactive({ name: "", description: "", saving: false });
const editing = reactive({ id: null as number | null, name: "", description: "" });

async function load(): Promise<void> {
  loadError.value = "";
  try {
    [roles.value, permissions.value] = await Promise.all([adminClient.listRoles(), adminClient.listPermissions()]);
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

function replace(updated: Role): void {
  roles.value = roles.value.map((r) => (r.id === updated.id ? updated : r));
}

/** Runs one admin call for `role`. When the logged-in account holds the
 * role, its permissions may have changed, so the account is re-read. */
async function act(role: Role, call: () => Promise<void>): Promise<void> {
  actionError.value = "";
  busyId.value = role.id;
  const held = auth.account?.roles.includes(role.name) ?? false;
  try {
    await call();
    if (held) await auth.refresh();
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    busyId.value = null;
  }
}

async function createRole(): Promise<void> {
  actionError.value = "";
  newRole.saving = true;
  try {
    const role = await adminClient.createRole(newRole.name.trim(), newRole.description.trim() || null);
    roles.value = [...roles.value, role].sort((a, b) => a.name.localeCompare(b.name));
    newRole.name = "";
    newRole.description = "";
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    newRole.saving = false;
  }
}

function togglePermission(role: Role, name: string, event: Event): Promise<void> {
  // Put the box back until ember_api answers: on success the new role data
  // re-renders it, on failure it stays as the server has it.
  const box = event.target as HTMLInputElement;
  const granted = box.checked;
  box.checked = !granted;
  return act(role, async () => {
    replace(
      granted ? await adminClient.grantPermission(role.id, name) : await adminClient.revokePermission(role.id, name),
    );
  });
}

function startEdit(role: Role): void {
  editing.id = role.id;
  editing.name = role.name;
  editing.description = role.description ?? "";
}

function saveEdit(role: Role): Promise<void> {
  const changes: RoleChanges = {};
  if (!role.is_protected && editing.name.trim() !== role.name) changes.name = editing.name.trim();
  if (editing.description.trim() !== (role.description ?? "")) changes.description = editing.description.trim();
  return act(role, async () => {
    if (Object.keys(changes).length) replace(await adminClient.updateRole(role.id, changes));
    editing.id = null;
  });
}

function remove(role: Role): Promise<void> | undefined {
  const users = role.account_count === 1 ? "1 account" : `${role.account_count} accounts`;
  if (!confirm(`Delete role '${role.name}'? It is removed from ${users}.`)) return;
  return act(role, async () => {
    await adminClient.deleteRole(role.id);
    roles.value = roles.value.filter((r) => r.id !== role.id);
  });
}

onMounted(load);
</script>

<template>
  <div class="admin-panel">
    <form class="row-form" @submit.prevent="createRole">
      <input v-model="newRole.name" type="text" placeholder="New role name" maxlength="80" required />
      <input v-model="newRole.description" type="text" placeholder="Description (optional)" maxlength="255" />
      <button class="primary" :disabled="newRole.saving || !newRole.name.trim()">Create role</button>
    </form>

    <p v-if="loadError" class="error">error: {{ loadError }}</p>
    <p v-if="actionError" class="error">{{ actionError }}</p>

    <h3>Roles</h3>
    <div v-for="r in roles" :key="r.id" class="card">
      <form v-if="editing.id === r.id" class="row-form" @submit.prevent="saveEdit(r)">
        <input
          v-model="editing.name"
          type="text"
          aria-label="Role name"
          maxlength="80"
          required
          :disabled="r.is_protected"
        />
        <input v-model="editing.description" type="text" aria-label="Description" maxlength="255" />
        <button class="primary" :disabled="busyId === r.id">Save</button>
        <button type="button" class="small" @click="editing.id = null">Cancel</button>
      </form>
      <template v-else>
        <div class="card-head">
          <span class="card-title">{{ r.name }}</span>
          <span v-if="r.is_protected" class="badge">protected</span>
          <span class="muted">{{ r.account_count }} {{ r.account_count === 1 ? "account" : "accounts" }}</span>
        </div>
        <p v-if="r.description" class="description muted">{{ r.description }}</p>
      </template>

      <div class="permissions">
        <label v-for="p in permissions" :key="p.name" :title="p.description ?? ''">
          <input
            type="checkbox"
            :checked="r.permissions.includes(p.name)"
            :disabled="r.is_protected || busyId === r.id"
            @change="togglePermission(r, p.name, $event)"
          />
          <code>{{ p.name }}</code>
          <span v-if="p.description" class="muted">{{ p.description }}</span>
        </label>
      </div>

      <div class="actions">
        <button type="button" class="small" :disabled="busyId === r.id" @click="startEdit(r)">Edit</button>
        <button
          v-if="!r.is_protected"
          type="button"
          class="small danger"
          :disabled="busyId === r.id"
          @click="remove(r)"
        >
          Delete
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.description {
  margin: 4px 0 0;
  font-size: 0.9em;
}
.permissions {
  display: grid;
  gap: 4px;
  margin-top: 10px;
}
.permissions label {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  font-size: 0.9em;
}
.permissions code {
  font-family: var(--mono);
}
</style>
