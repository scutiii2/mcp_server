<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import type { PermissionInfo, Role, RoleChanges } from "../../api/AdminClient";
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
}>();

const emit = defineEmits<{
  save: [changes: RoleChanges];
  togglePermission: [name: string, granted: boolean];
  remove: [];
}>();

const editing = ref(false);
const form = reactive({ name: "", description: "" });

// A different role starts with the edit form closed.
watch(
  () => props.role.id,
  () => (editing.value = false),
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
    </header>
    <p v-if="!editing && role.description" class="muted description">{{ role.description }}</p>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="role.is_protected" class="muted note">This role always holds every permission and can't be renamed or deleted.</p>

    <ul class="permissions">
      <li v-for="p in permissions" :key="p.name">
        <ToggleSwitch
          small
          :checked="role.permissions.includes(p.name)"
          :disabled="role.is_protected || busy"
          :aria-label="p.name"
          @click.prevent="emit('togglePermission', p.name, !role.permissions.includes(p.name))"
        />
        <div>
          <code>{{ p.name }}</code>
          <div v-if="p.description" class="muted description">{{ p.description }}</div>
        </div>
      </li>
    </ul>

    <div class="actions">
      <button v-if="!editing" type="button" class="small" :disabled="busy" @click="startEdit">
        {{ role.is_protected ? "Edit description" : "Edit details" }}
      </button>
    </div>

    <section v-if="!role.is_protected" class="danger-zone">
      <h4>Danger zone</h4>
      <p class="muted description">Accounts holding this role lose its permissions. This can't be undone.</p>
      <button type="button" class="small danger" :disabled="busy" @click="emit('remove')">Delete role</button>
    </section>
  </section>
</template>

<style scoped>
.editor {
  min-width: 0;
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
.permissions {
  display: flex;
  flex-direction: column;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}
.permissions li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--border);
}
.permissions code {
  font-family: var(--mono);
  font-size: 0.9em;
}
</style>
