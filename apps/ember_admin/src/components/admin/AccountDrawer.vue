<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { AccountChanges, AdminAccount, Role, RoleRef } from "../../api/AdminClient";
import { useAuthStore } from "../../stores/auth";
import { formatUtc } from "../../utils/errors";
import ToggleSwitch from "../ToggleSwitch.vue";
import "./admin.css";

/** Everything one account offers: edit details, roles, enable/disable, send
 * verification, delete. It only shows state and reports what the admin chose
 * (the parent runs the call and asks for confirmation); `busy` disables the
 * controls while a call is in flight. */
const props = withDefaults(defineProps<{
  account: AdminAccount;
  roles: Role[];
  isSelf: boolean;
  busy: boolean;
  error: string;
  notice: string;
  showClose?: boolean;
}>(), { showClose: true });

const emit = defineEmits<{
  close: [];
  save: [changes: AccountChanges];
  setActive: [active: boolean];
  addRole: [roleId: number];
  removeRole: [role: RoleRef];
  sendVerification: [];
  remove: [];
}>();

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission("accounts.manage"));
const canAssign = computed(() => auth.hasPermission("roles.assign"));
const editing = ref(false);
const form = reactive({ username: "", email: "" });

// A different account starts with the edit form closed.
watch(
  () => props.account.id,
  () => (editing.value = false),
);

const missingRoles = computed(() => {
  const held = new Set(props.account.roles.map((r) => r.id));
  return props.roles.filter((r) => !held.has(r.id) && r.permissions.every(auth.hasPermission));
});

/** Protected accounts can't be changed at all; your own can't be disabled or deleted. */
const locked = computed(() => props.account.is_protected);
const canDisable = computed(() => canManage.value && !locked.value && !props.isSelf);

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
      <div class="identity">
        <span class="avatar" aria-hidden="true">{{ account.username.slice(0, 2).toUpperCase() }}</span>
        <div class="who">
          <b class="name">{{ account.username }}</b>
          <span v-if="isSelf" class="self-label">Your account</span>
        </div>
      </div>
      <button v-if="showClose" type="button" class="x" aria-label="Close" @click="emit('close')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </header>
    <div class="profile-meta">
      <p class="account-email">{{ account.email }}</p>
      <p class="joined"><span>Joined</span><time>{{ formatUtc(account.created_at) }}</time></p>
    </div>

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

    <section class="roles-section">
      <h4>Roles</h4>
      <div class="chips">
        <span v-for="r in account.roles" :key="r.id" class="chip" :class="{ fixed: locked }">
          {{ r.name }}
          <button
            v-if="!locked && canAssign"
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
      </div>
      <select v-if="!locked && canAssign && missingRoles.length" class="add-role" aria-label="Role to add" :disabled="busy" @change="onAddRole">
        <option value="">+ Add role</option>
        <option v-for="r in missingRoles" :key="r.id" :value="r.id">{{ r.name }}</option>
      </select>
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
      <button v-if="!editing && canManage" type="button" class="small" :disabled="busy" @click="startEdit">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16 3a2.1 2.1 0 0 1 3 3L7 18l-4 1 1-4z" /></svg>
        Edit details
      </button>
      <button v-if="!account.email_verified && canManage" type="button" class="small" :disabled="busy" @click="emit('sendVerification')">
        Send verification
      </button>
    </div>

    <section v-if="!locked && !isSelf && auth.hasPermission('accounts.delete')" class="danger-zone">
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
  gap: 0;
  padding: 0;
  background: var(--bg);
}
.identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.avatar {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  border-radius: var(--radius-full);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, var(--surface));
  font-size: 0.85em;
  font-weight: 600;
}
.drawer > section:not(.danger-zone) {
  padding-top: 18px;
  margin-top: 18px;
  border-top: 1px solid var(--border);
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
.name {
  font-size: 1.05em;
  font-weight: 600;
}
.self-label {
  color: var(--muted);
  font-size: 0.75em;
  margin-top: 2px;
}
.profile-meta {
  margin-top: 14px;
}
.account-email {
  margin: 0;
  font-size: 0.85em;
  overflow-wrap: anywhere;
}
.joined {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 0.75em;
}
.joined > span {
  font-size: 0.9em;
}
.drawer > .error, .drawer > .notice, .drawer > .small-text {
  margin: 14px 0 0;
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
  margin: 0 0 12px;
  font-size: 0.85em;
  font-weight: 600;
}
.x {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  padding: 4px;
  border: none;
  border-radius: var(--radius-md);
  background: none;
  cursor: pointer;
  color: var(--muted);
}
.x svg { width: 16px; height: 16px; }
.x:hover { color: var(--text); background: var(--bg); }
.edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 18px;
}
.row {
  display: flex;
  gap: 8px;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 20px;
}
.drawer .buttons > button.small {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 36px;
  padding: 7px 12px;
  border-radius: var(--radius-md);
  background: var(--bg);
}
.buttons svg { width: 15px; height: 15px; }
.drawer .chips {
  margin-top: 0;
  gap: 8px;
}
.drawer .chip {
  gap: 8px;
  padding: 5px 6px 5px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  overflow-wrap: anywhere;
  max-width: 100%;
}
.drawer .chip.fixed { padding-right: 10px; }
.drawer select.add-role {
  display: block;
  width: 100%;
  min-width: 0;
  margin-top: 12px;
  padding: 8px 10px;
  font-size: 0.85em;
  cursor: pointer;
}
</style>
