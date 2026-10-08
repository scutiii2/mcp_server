<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { PermissionInfo, Role, RoleChanges } from "../../api/AdminClient";
import { useAuthStore } from "../../stores/auth";
import ToggleSwitch from "../ToggleSwitch.vue";
import "./admin.css";

/** One role: its name and description, a switch per permission, and delete.
 * It only shows state and reports what the admin chose (the parent runs the
 * call and asks for confirmation); `busy` disables the controls while a call
 * is in flight. */
const props = defineProps<{
  role: Role;
  permissions: PermissionInfo[];
  busy: boolean;
  error: string;
  /** The last change went through. */
  saved?: boolean;
}>();

const emit = defineEmits<{
  save: [changes: RoleChanges];
  togglePermission: [name: string, granted: boolean];
  remove: [];
}>();

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission("roles.manage") && props.role.permissions.every(auth.hasPermission));
const editing = ref(false);
const form = reactive({ name: "", description: "" });
const search = ref("");
const labels: Record<string, string> = {
  "chat.use": "Use chat", "chat.share": "Share chats publicly", "files.upload": "Upload files", "files.download": "Download files",
  "tools.view": "Browse tools", "tools.execute": "Run tools", "extensions.personal.manage": "Manage personal extensions",
  "accounts.view": "View accounts", "accounts.manage": "Manage accounts", "accounts.delete": "Delete accounts",
  "roles.view": "View roles", "roles.manage": "Manage roles & permissions", "roles.assign": "Assign roles", "invites.manage": "Manage invites",
  "settings.manage": "Manage workspace settings", "capabilities.manage": "Manage shared capabilities", "extensions.manage": "Manage shared extensions",
  "usage.all.view": "View all account usage", "watchers.view": "View watchers", "logs.view": "View activity logs", "logs.errors.view": "View error logs",
  "logs.chat.view": "View chat logs", "config.issues.view": "View configuration issues", "traffic.view": "View network traffic",
};
const groups = computed(() => {
  const definitions = [
    { label: "Chat & files", names: ["chat.use", "chat.share", "files.upload", "files.download"] },
    { label: "Tools & personal extensions", names: ["tools.view", "tools.execute", "extensions.personal.manage"] },
    { label: "Accounts & access", names: ["accounts.view", "accounts.manage", "accounts.delete", "roles.view", "roles.manage", "roles.assign", "invites.manage"] },
    { label: "Workspace & monitoring", names: ["settings.manage", "capabilities.manage", "extensions.manage", "usage.all.view", "watchers.view", "logs.view", "logs.errors.view", "logs.chat.view", "config.issues.view", "traffic.view"] },
  ];
  const known = new Set(definitions.flatMap((g) => g.names));
  definitions.push({ label: "Other permissions", names: props.permissions.filter((p) => !known.has(p.name)).map((p) => p.name) });
  const query = search.value.trim().toLowerCase();
  return definitions.map((group) => {
    const all = props.permissions.filter((p) => group.names.includes(p.name));
    return {
      label: group.label,
      total: all.length,
      enabled: all.filter((p) => props.role.permissions.includes(p.name)).length,
      permissions: all.filter((p) => `${labels[p.name] ?? ''} ${p.name} ${p.description ?? ''}`.toLowerCase().includes(query)),
    };
  }).filter((g) => g.permissions.length);
});

// A different role starts with the edit form closed.
watch(
  () => props.role.id,
  () => { editing.value = false; search.value = ""; },
);

function startEdit(): void {
  form.name = props.role.name;
  form.description = props.role.description ?? "";
  editing.value = true;
}

function save(): void {
  const changes: RoleChanges = {};
  if (!props.role.is_protected && form.name.trim() !== props.role.name) changes.name = form.name.trim();
  if (form.description.trim() !== (props.role.description ?? "")) changes.description = form.description.trim();
  if (Object.keys(changes).length) emit("save", changes);
  editing.value = false;
}
</script>

<template>
  <section class="editor admin-panel" :aria-label="`Role ${role.name}`">
    <form v-if="editing" class="row-form" @submit.prevent="save">
      <input v-model="form.name" type="text" aria-label="Role name" maxlength="80" required :disabled="role.is_protected" />
      <input v-model="form.description" type="text" aria-label="Description" maxlength="255" />
      <button class="primary" :disabled="busy">Save</button>
      <button type="button" class="small" @click="editing = false">Cancel</button>
    </form>
    <header v-else>
      <b class="name">{{ role.name }}</b>
      <span v-if="role.is_protected" class="badge">protected</span>
      <span class="muted count">{{ role.account_count }} {{ role.account_count === 1 ? "account" : "accounts" }}</span>
      <button v-if="canManage" type="button" class="small" :disabled="busy" @click="startEdit">{{ role.is_protected ? "Edit description" : "Edit details" }}</button>
    </header>
    <p v-if="!editing && role.description" class="muted description">{{ role.description }}</p>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="role.is_protected" class="muted note">This role always holds every permission and can't be renamed or deleted.</p>
    <p v-else-if="!canManage" class="muted note">Read-only. Editing requires role management access and every permission held by this role.</p>

    <p v-if="!role.is_protected" class="impact">Changes apply to {{ role.account_count }} {{ role.account_count === 1 ? 'account' : 'accounts' }}.</p>
    <p class="apply muted" role="status">
      <span>Permission switches apply instantly.</span>
      <span v-if="busy">Saving…</span>
      <span v-if="saved && !error" class="chip saved" role="status">Saved</span>
    </p>

    <p class="muted description">Each switch saves after the server confirms the change.</p>
    <label class="permission-search"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0" /></svg><input v-model="search" type="search" placeholder="Find a permission" aria-label="Find a permission" /></label>
    <section v-for="group in groups" :key="group.label" class="permission-group" :aria-label="group.label">
      <div class="group-head"><h4>{{ group.label }}</h4><span>{{ group.enabled }} of {{ group.total }} enabled</span></div>
      <ul class="permissions" :aria-busy="busy">
      <li v-for="p in group.permissions" :key="p.name">
        <ToggleSwitch
          small
          :checked="role.permissions.includes(p.name)"
          :disabled="role.is_protected || busy || !canManage || !auth.hasPermission(p.name)"
          :aria-label="p.name"
          @click.prevent="emit('togglePermission', p.name, !role.permissions.includes(p.name))"
        />
        <div>
          <strong class="permission-label">{{ labels[p.name] ?? p.name }}</strong>
          <code>{{ p.name }}</code>
          <div v-if="p.description" class="muted description">{{ p.description }}</div>
        </div>
      </li>
      </ul>
    </section>
    <p v-if="!groups.length" class="muted">No permissions match your search.</p>

    <section v-if="!role.is_protected && canManage" class="danger-zone">
      <h4>Danger zone</h4>
      <p class="muted description">Accounts holding this role lose its permissions. This can't be undone.</p>
      <button type="button" class="small danger" :disabled="busy" @click="emit('remove')">Delete role</button>
    </section>
  </section>
</template>

<style scoped>
.editor {
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg);
}
header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 10px;
}
.name {
  font-size: 1.05em;
  overflow-wrap: anywhere;
}
.count {
  margin-left: auto;
  font-size: 0.85em;
}
.description {
  margin: 2px 0 0;
  font-size: 0.85em;
}
.note {
  margin: 8px 0 0;
  font-size: 0.85em;
}
.apply {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0;
  font-size: 0.85em;
}
.chip.saved {
  color: var(--success);
  border-color: var(--success);
}
.permissions {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.permissions li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-top: 1px solid var(--border);
}
.permissions li > div { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.permissions li > .toggle { order: 1; flex-shrink: 0; }
.permission-label { display: block; font-size: 0.9em; font-weight: 500; }
.impact { margin: 16px 0 0; padding: 12px 14px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); font-size: 0.9em; }
.permission-search { display: flex; align-items: center; gap: 10px; margin: 16px 0; padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); }
.permission-search svg { width: 17px; height: 17px; color: var(--muted); flex-shrink: 0; }
.permission-search input { width: 100%; min-width: 0; border: none; background: transparent; font: inherit; font-size: 0.85em; }
.permission-group { margin-top: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; }
.group-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; background: var(--surface); }
.group-head h4 { margin: 0; font-size: 0.85em; }
.group-head span { color: var(--muted); font-size: 0.75em; white-space: nowrap; }
.permissions code {
  font-family: var(--mono);
  font-size: 0.9em;
}
</style>
