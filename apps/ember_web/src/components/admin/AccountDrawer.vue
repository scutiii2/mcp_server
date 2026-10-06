<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { AccountChanges, AdminAccount, Role, RoleRef } from "../../api/AdminClient";
import { formatUtc } from "../../utils/errors";
import ToggleSwitch from "../ToggleSwitch.vue";
import "./admin.css";

/** Everything one account offers: edit details, roles, enable/disable, send
 * verification, delete. It only shows state and reports what the admin chose
 * (the parent runs the call and asks for confirmation); `busy` disables the
 * controls while a call is in flight. */
const props = defineProps<{
  account: AdminAccount;
  roles: Role[];
  isSelf: boolean;
  busy: boolean;
  error: string;
  notice: string;
}>();

const emit = defineEmits<{
  close: [];
  save: [changes: AccountChanges];
  setActive: [active: boolean];
  addRole: [roleId: number];
  removeRole: [role: RoleRef];
  sendVerification: [];
  remove: [];
}>();

const editing = ref(false);
const form = reactive({ username: "", email: "" });

// A different account starts with the edit form closed.
watch(
  () => props.account.id,
  () => (editing.value = false),
);

const missingRoles = computed(() => {
  const held = new Set(props.account.roles.map((r) => r.id));
  return props.roles.filter((r) => !held.has(r.id));
});

/** Protected accounts can't be changed at all; your own can't be disabled or deleted. */
const locked = computed(() => props.account.is_protected);
const canDisable = computed(() => !locked.value && !props.isSelf);

function startEdit(): void {
  form.username = props.account.username;
  form.email = props.account.email;
  editing.value = true;
}

function save(): void {
  const changes: AccountChanges = {};
  if (form.username.trim() !== props.account.username) changes.username = form.username.trim();
  if (form.email.trim() !== props.account.email) changes.email = form.email.trim();
  if (Object.keys(changes).length) emit("save", changes);
  editing.value = false;
}

function onAddRole(event: Event): void {
  const select = event.target as HTMLSelectElement;
  const roleId = Number(select.value);
  select.value = "";
  if (roleId) emit("addRole", roleId);
}
</script>

<template>
  <aside class="drawer admin-panel" :aria-label="`Account ${account.username}`">
    <header>
      <div class="who">
        <b class="name">{{ account.username }}</b>
        <span class="muted small-text">{{ account.email }}</span>
      </div>
      <button type="button" class="x" aria-label="Close" @click="emit('close')">×</button>
    </header>
    <p class="muted small-text">Joined {{ formatUtc(account.created_at) }}</p>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <p v-if="locked" class="muted small-text">This is the protected admin account. It can't be edited, disabled or deleted.</p>

    <form v-if="editing" class="edit" @submit.prevent="save">
      <input v-model="form.username" type="text" aria-label="Username" required />
      <input v-model="form.email" type="email" aria-label="Email" required />
      <div class="row">
        <button class="primary" :disabled="busy">Save</button>
        <button type="button" class="small" @click="editing = false">Cancel</button>
      </div>
    </form>

    <section>
      <h4>Roles</h4>
      <div class="chips">
        <span v-for="r in account.roles" :key="r.id" class="chip" :class="{ fixed: locked }">
          {{ r.name }}
          <button
            v-if="!locked"
            type="button"
            class="chip-x"
            :aria-label="`Remove role ${r.name}`"
            :disabled="busy"
            @click="emit('removeRole', r)"
          >
            ×
          </button>
        </span>
        <span v-if="account.roles.length === 0" class="muted">No roles</span>
        <select v-if="!locked && missingRoles.length" aria-label="Role to add" :disabled="busy" @change="onAddRole">
          <option value="">+ Add role</option>
          <option v-for="r in missingRoles" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </div>
    </section>

    <section v-if="canDisable">
      <ToggleSwitch
        small
        :checked="account.is_active"
        :disabled="busy"
        @click.prevent="emit('setActive', !account.is_active)"
      >
        Active
      </ToggleSwitch>
    </section>

    <div v-if="!locked" class="buttons">
      <button v-if="!editing" type="button" class="small" :disabled="busy" @click="startEdit">Edit details</button>
      <button v-if="!account.email_verified" type="button" class="small" :disabled="busy" @click="emit('sendVerification')">
        Send verification
      </button>
    </div>

    <section v-if="!locked && !isSelf" class="danger-zone">
      <h4>Danger zone</h4>
      <p class="muted small-text">Removes the account for good. This can't be undone.</p>
      <button type="button" class="small danger" :disabled="busy" @click="emit('remove')">Delete account</button>
    </section>
  </aside>
</template>

<style scoped>
.drawer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.who {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.name,
.who span {
  overflow-wrap: anywhere;
}
.small-text {
  margin: 0;
  font-size: 0.85em;
}
h4 {
  margin: 0 0 6px;
  font-size: 0.8em;
  font-weight: 500;
  color: var(--muted);
}
.x {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1.4em;
  line-height: 1;
  color: var(--muted);
}
.edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  gap: 8px;
}
.buttons {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}
.chips {
  margin-top: 0;
}
@media (max-width: 720px) {
  .drawer {
    position: fixed;
    inset: auto 0 0 0;
    z-index: 5;
    max-height: 75vh;
    overflow-y: auto;
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  }
}
</style>
